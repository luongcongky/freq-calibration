"""
drivers/base_visa.py
====================
Lớp truyền dẫn VISA dùng chung cho TẤT CẢ driver thiết bị.

Mục đích: gom phần "plumbing" lặp đi lặp lại (mở/đóng VISA session, mock mode,
_write/_query, đọc error queue, *IDN?, *RST, get_status khung) vào một nơi.

QUAN TRỌNG: Đây KHÔNG phải driver-generic-điều-khiển-bằng-bảng. Mỗi model thiết
bị vẫn là một class driver chuyên biệt riêng (xem keysight_counters.py,
pendulum_counters.py, ...), kế thừa lớp này CHỈ để dùng lại phần kết nối I/O.
Tập lệnh điều khiển / thu thập của từng máy nằm trong chính class của máy đó.

Mock mode
---------
Khi `mock=True`, không mở VISA. Mỗi driver con override `_mock_response(cmd)` để
trả về chuỗi giả lập đúng "giọng" của máy thật (ví dụ *IDN? trả đúng model).
Nhờ vậy toàn bộ test có thể chạy offline, không cần phần cứng.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import pyvisa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions dùng chung
# ---------------------------------------------------------------------------

class InstrumentError(Exception):
    """Base exception cho mọi driver thiết bị."""


class ConnectionError_(InstrumentError):
    """Không mở được kết nối tới thiết bị."""


class CommandError(InstrumentError):
    """Thiết bị báo lỗi trong error queue / lệnh không hợp lệ."""


class MeasurementError(InstrumentError):
    """Phép đo thất bại hoặc không parse được kết quả."""


class IdentificationError(InstrumentError):
    """*IDN? trả về model không khớp với driver đang dùng."""


# ---------------------------------------------------------------------------
# Kết quả đo dùng chung
# ---------------------------------------------------------------------------

@dataclass
class Reading:
    """Một giá trị đo đơn kèm metadata (Hz, dBm, W, s, ...)."""
    value: float
    unit: str
    timestamp: float = field(default_factory=time.time)
    channel: int = 1
    raw: str = ""

    def __str__(self) -> str:
        return f"Reading(value={self.value:.9g} {self.unit}, ch={self.channel})"


# ---------------------------------------------------------------------------
# Lớp transport
# ---------------------------------------------------------------------------

class VisaInstrument:
    """
    Lớp nền quản lý phiên VISA + mock cho các driver con.

    Driver con CẦN khai báo (class attribute):
        IDN_KEYWORDS : tuple[str, ...]   – các chuỗi nhận diện trong *IDN? (vd: ("53131A",))
        MODEL_NAME   : str               – tên model hiển thị (vd: "Keysight 53131A")

    Driver con NÊN override:
        _mock_response(cmd) -> str       – trả lời giả lập cho mock mode
    """

    IDN_KEYWORDS: tuple[str, ...] = ()
    MODEL_NAME: str = "Generic VISA Instrument"

    # SCPI mặc định cho thiết bị tuân IEEE-488.2. Máy đời cũ (Boonton, Advantest)
    # sẽ override các hằng này / tự cài đặt riêng.
    CMD_IDN = "*IDN?"
    CMD_RST = "*RST"
    CMD_CLS = "*CLS"
    CMD_ERR = "SYST:ERR?"
    SUPPORTS_SCPI_ERR_QUEUE = True

    DEFAULT_TIMEOUT_MS = 10_000

    def __init__(
        self,
        resource_address: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        reset_on_connect: bool = False,
        visa_backend: str = "",
        mock: bool = False,
        strict_idn: bool = False,
    ):
        """
        Parameters
        ----------
        resource_address : str
            Chuỗi tài nguyên VISA. Ví dụ:
              "GPIB0::7::INSTR"
              "TCPIP0::100.64.0.3::gpib0,7::INSTR"   (VISA-over-IP qua Tailscale)
        timeout_ms : int
            Timeout I/O (ms). Tăng lên khi gate time / averaging dài.
        reset_on_connect : bool
            Gửi *RST ngay khi kết nối.
        visa_backend : str
            Override backend pyvisa, ví dụ "@py" (pyvisa-py) hoặc "@sim".
        mock : bool
            Chạy mô phỏng, không mở VISA. Dùng cho test offline.
        strict_idn : bool
            Nếu True và *IDN? không chứa IDN_KEYWORDS -> raise IdentificationError.
            Nếu False -> chỉ ghi cảnh báo (mặc định, vì máy đời cũ IDN khác nhau).
        """
        self._address = resource_address
        self._timeout_ms = timeout_ms
        self._reset_on_connect = reset_on_connect
        self._visa_backend = visa_backend
        self._mock = mock
        self._strict_idn = strict_idn

        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.resources.MessageBasedResource] = None

        self.connect()

    # ------------------------------------------------------------------
    # Quản lý kết nối
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Mở phiên VISA (bỏ qua nếu mock) và xác thực IDN."""
        if self._mock:
            logger.info("%s: MOCK mode (không mở VISA).", self.MODEL_NAME)
            return

        try:
            self._rm = (
                pyvisa.ResourceManager(self._visa_backend)
                if self._visa_backend
                else pyvisa.ResourceManager()
            )
            self._inst = self._rm.open_resource(self._address)
            self._inst.timeout = self._timeout_ms
            self._inst.read_termination = "\n"
            self._inst.write_termination = "\n"
        except pyvisa.VisaIOError as exc:
            raise ConnectionError_(
                f"{self.MODEL_NAME}: không kết nối được tới '{self._address}': {exc}"
            ) from exc

        self._verify_identity()

        if self._reset_on_connect:
            self.reset()

    def _verify_identity(self) -> None:
        """Đọc *IDN? và kiểm tra có đúng model không."""
        try:
            idn = self.identify()
        except Exception as exc:  # noqa: BLE001
            if self._strict_idn:
                raise IdentificationError(
                    f"{self.MODEL_NAME}: không đọc được *IDN?: {exc}"
                ) from exc
            logger.warning("%s: không đọc được *IDN? (%s).", self.MODEL_NAME, exc)
            return

        if self.IDN_KEYWORDS and not any(k in idn for k in self.IDN_KEYWORDS):
            msg = (
                f"{self.MODEL_NAME}: *IDN? = '{idn.strip()}' không chứa "
                f"từ khóa nhận diện {self.IDN_KEYWORDS}."
            )
            if self._strict_idn:
                raise IdentificationError(msg)
            logger.warning(msg)
        else:
            logger.info("%s: kết nối OK -> %s", self.MODEL_NAME, idn.strip())

    def disconnect(self) -> None:
        """Đóng phiên VISA an toàn."""
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:  # noqa: BLE001
                pass
            self._inst = None
        if self._rm is not None:
            try:
                self._rm.close()
            except Exception:  # noqa: BLE001
                pass
            self._rm = None
        logger.info("%s: đã ngắt kết nối.", self.MODEL_NAME)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()

    @property
    def is_mock(self) -> bool:
        return self._mock

    @property
    def address(self) -> str:
        return self._address

    # ------------------------------------------------------------------
    # I/O cấp thấp
    # ------------------------------------------------------------------

    def _write(self, cmd: str) -> None:
        """Gửi một lệnh (bỏ qua I/O thật nếu mock)."""
        logger.debug("[%s] WRITE >> %s", self.MODEL_NAME, cmd)
        if self._mock:
            self._mock_write(cmd)
            return
        self._inst.write(cmd)

    def _query(self, cmd: str, timeout_override_ms: Optional[int] = None) -> str:
        """Gửi query, trả về chuỗi đã strip (trả lời giả nếu mock)."""
        logger.debug("[%s] QUERY >> %s", self.MODEL_NAME, cmd)
        if self._mock:
            resp = self._mock_response(cmd)
            logger.debug("[%s] MOCK  << %s", self.MODEL_NAME, resp)
            return resp

        old = None
        if timeout_override_ms is not None:
            old = self._inst.timeout
            self._inst.timeout = timeout_override_ms
        try:
            response = self._inst.query(cmd).strip()
        finally:
            if old is not None:
                self._inst.timeout = old
        logger.debug("[%s] RESP  << %s", self.MODEL_NAME, response)
        return response

    def set_timeout(self, timeout_ms: int) -> None:
        """Đổi timeout I/O hiện hành (no-op khi mock)."""
        self._timeout_ms = timeout_ms
        if not self._mock and self._inst is not None:
            self._inst.timeout = timeout_ms

    # ------------------------------------------------------------------
    # Mock hooks — driver con override để mô phỏng máy thật
    # ------------------------------------------------------------------

    def _mock_response(self, cmd: str) -> str:
        """Trả lời mặc định khi mock. Driver con NÊN override."""
        if "*IDN?" in cmd or self.CMD_IDN in cmd:
            return self._mock_idn()
        if "*OPC?" in cmd:
            return "1"
        if self.CMD_ERR in cmd:
            return '0,"No error"'
        return "0"

    def _mock_write(self, cmd: str) -> None:
        """Xử lý ghi khi mock (mặc định bỏ qua). Override nếu cần lưu state."""
        return None

    def _mock_idn(self) -> str:
        """Chuỗi *IDN? giả lập. Driver con NÊN override cho đúng model."""
        return f"MOCK,{self.MODEL_NAME},SN-MOCK,1.0"

    # ------------------------------------------------------------------
    # Định danh & housekeeping
    # ------------------------------------------------------------------

    def identify(self) -> str:
        """Trả về chuỗi *IDN? thô."""
        return self._query(self.CMD_IDN)

    def get_model(self) -> str:
        """
        Lấy tên model 'sạch' từ *IDN?.

        *IDN? chuẩn IEEE-488.2 có dạng: <Manufacturer>,<Model>,<Serial>,<FW>.
        Trả về trường model (phần tử thứ 2) nếu tách được, ngược lại trả nguyên chuỗi.
        """
        idn = self.identify()
        parts = [p.strip() for p in idn.split(",")]
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return idn.strip()

    def reset(self) -> None:
        """Gửi *RST."""
        self._write(self.CMD_RST)
        logger.info("%s: *RST.", self.MODEL_NAME)

    def clear_status(self) -> None:
        """Gửi *CLS."""
        self._write(self.CMD_CLS)

    def wait_for_completion(self, timeout_s: float = 60.0) -> None:
        """Chờ *OPC? == 1."""
        if self._mock:
            return
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self._query("*OPC?", timeout_override_ms=2000) == "1":
                    return
            except pyvisa.VisaIOError:
                pass
            time.sleep(0.2)
        raise InstrumentError(f"{self.MODEL_NAME}: timeout chờ *OPC.")

    # ------------------------------------------------------------------
    # Error queue / status
    # ------------------------------------------------------------------

    def get_all_errors(self) -> list[str]:
        """Đọc cạn error queue (SCPI). Trả [] nếu máy không hỗ trợ."""
        if not self.SUPPORTS_SCPI_ERR_QUEUE:
            return []
        errors: list[str] = []
        for _ in range(50):
            err = self._query(self.CMD_ERR)
            if err.startswith("0") or err.startswith("+0"):
                break
            errors.append(err)
        return errors

    def get_status(self) -> dict:
        """
        Ảnh chụp trạng thái cơ bản. Driver con NÊN mở rộng (thêm gate time,
        kênh, tần số cal, v.v.).
        """
        return {
            "model_name": self.MODEL_NAME,
            "address": self._address,
            "mock": self._mock,
            "idn": self.identify(),
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}(address='{self._address}', mock={self._mock})"
