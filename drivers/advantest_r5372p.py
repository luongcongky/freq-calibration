"""
drivers/advantest_r5372p.py
===========================
Driver cho máy đếm tần số cao tần/siêu cao tần Advantest R5372P.

CẢNH BÁO (legacy, best-effort):
    Dòng Advantest R5372 đời cũ KHÔNG dùng SCPI chuẩn mà dùng tập lệnh GPIB
    riêng của Advantest (mã lệnh ngắn dạng ký tự, ví dụ chọn hàm/định dạng,
    rồi đọc kết quả khi được addressed-to-talk). Nhiều máy đời này KHÔNG hỗ
    trợ *IDN?.

    Toàn bộ chuỗi lệnh dưới đây là PLACEHOLDER theo hiểu biết chung và được
    đánh dấu TODO(hardware). PHẢI đối chiếu "R5372P Operation/GPIB Manual"
    và chỉnh lại các hằng số CMD_* trước khi chạy trên máy thật.

3 thao tác giai đoạn 1 (chạy được ở mock; cần chỉnh khi gặp máy thật):
    1. connect + nhận diện  -> identify() (fallback nếu không có *IDN?)
    2. CONTROL  -> set_gate_time()
    3. ACQUIRE  -> measure_frequency()
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)


class AdvantestR5372P(VisaInstrument):
    """Advantest R5372P Microwave Frequency Counter (legacy, non-SCPI)."""

    IDN_KEYWORDS = ("R5372", "ADVANTEST")
    MODEL_NAME = "Advantest R5372P"

    # Máy đời cũ: không chắc có error queue SCPI, không strict IDN.
    SUPPORTS_SCPI_ERR_QUEUE = False

    # ---- Tập lệnh PLACEHOLDER — TODO(hardware): thay theo manual R5372P ----
    CMD_IDN = "*IDN?"          # TODO(hardware): R5372P có thể không hỗ trợ; xem fallback identify()
    CMD_RST = "*RST"           # TODO(hardware)
    CMD_TRIGGER = "E"          # TODO(hardware): mã 'execute/measure' giả định
    CMD_READ = "?"             # TODO(hardware): cách đọc kết quả
    CMD_GATE_FMT = "GA {val}"  # TODO(hardware): cú pháp đặt gate/resolution
    # -----------------------------------------------------------------------

    DEFAULT_GATE_TIME_S = 1.0

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 1.8e10  # 18 GHz giả lập (siêu cao tần)
        # Không ép strict IDN với máy đời cũ.
        kwargs.setdefault("strict_idn", False)
        super().__init__(*args, **kwargs)

    # --- Nhận diện (có fallback) -------------------------------------
    def identify(self) -> str:
        """
        Thử *IDN?; nếu máy không hỗ trợ (lỗi/timeout) thì trả về định danh
        suy ra từ model thay vì raise — để bước connect không chết.
        """
        try:
            resp = self._query(self.CMD_IDN)
            if resp and resp != "0":
                return resp
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: *IDN? không khả dụng (%s).", self.MODEL_NAME, exc)
        return f"Advantest,R5372P,UNKNOWN,(no *IDN?)"

    # --- CONTROL -----------------------------------------------------
    def set_gate_time(self, gate_s: float) -> None:
        """
        Đặt gate/resolution. TODO(hardware): R5372P có thể đặt 'resolution'
        theo số chữ số thay vì gate thời gian — cần map lại theo manual.
        """
        if gate_s <= 0:
            raise ValueError("gate_time phải > 0")
        self._write(self.CMD_GATE_FMT.format(val=f"{gate_s:.6f}"))
        self._gate_time_s = gate_s
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s (best-effort)", self.MODEL_NAME, gate_s)

    # --- ACQUIRE -----------------------------------------------------
    def measure_frequency(self, channel: int = 1) -> Reading:
        """
        Kích hoạt đo và đọc kết quả tần số (Hz).

        TODO(hardware): nhiều máy Advantest ở chế độ talk sẽ tự xuất kết quả
        sau khi nhận lệnh trigger; khi đó có thể cần self._inst.read() thay vì
        query. Hiện dùng trigger + query placeholder để chạy được ở mock.
        """
        self._write(self.CMD_TRIGGER)
        raw = self._query(
            self.CMD_READ,
            timeout_override_ms=int(self._gate_time_s * 1000) + 5000,
        )
        value = self._parse_advantest_freq(raw)
        return Reading(value=value, unit="Hz", channel=channel, raw=raw)

    def _parse_advantest_freq(self, raw: str) -> float:
        """
        Parse chuỗi kết quả Advantest. TODO(hardware): máy đời cũ thường bọc
        giá trị trong header (vd 'FA  1.800000000E+10' hoặc kèm đơn vị). Hiện
        bóc số float đầu tiên tìm được.
        """
        token = raw.strip().replace(",", " ").split()
        for t in token:
            try:
                return float(t)
            except ValueError:
                continue
        # thử lấy phần số ở cuối (vd "FA1.8E10")
        try:
            return float(raw.strip().lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được tần số: '{raw}'"
            ) from exc

    def get_status(self) -> dict:
        st = super().get_status()
        st["gate_time_s"] = self._gate_time_s
        st["note"] = "legacy non-SCPI; lệnh là best-effort (xem TODO)."
        return st

    # --- Mock --------------------------------------------------------
    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if cmd.strip() == self.CMD_READ or "FREQ" in cmd.upper():
            import random
            return f"FA  {self._mock_freq + random.gauss(0, 50):.3f}"
        return "0"

    def _mock_idn(self) -> str:
        return "ADVANTEST,R5372P,00000001,REV1.0"
