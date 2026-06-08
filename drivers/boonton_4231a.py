"""
drivers/boonton_4231a.py
========================
Driver cho máy đo công suất cao tần Boonton 4231A.

CẢNH BÁO (legacy, best-effort):
    Boonton 4231A là máy đo công suất RF đời cũ, dùng tập lệnh GPIB ASCII riêng
    (KHÔNG phải SCPI) và thường KHÔNG hỗ trợ *IDN?. Khi được addressed-to-talk,
    máy xuất ra chuỗi kết quả đo.

    Toàn bộ mã lệnh CMD_* dưới đây là PLACEHOLDER, đánh dấu TODO(hardware).
    PHẢI đối chiếu "Boonton 4231A Instruction Manual (GPIB section)" và chỉnh
    lại trước khi chạy trên máy thật.

3 thao tác giai đoạn 1 (chạy ở mock; cần chỉnh khi gặp máy thật):
    1. connect + nhận diện  -> identify() (fallback nếu không có *IDN?)
    2. CONTROL  -> set_frequency()  (đặt tần số -> chọn cal factor)
    3. ACQUIRE  -> measure_power()  (đọc công suất, dBm)
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

FREQ_MIN_HZ = 1.0e3
FREQ_MAX_HZ = 40.0e9


class Boonton4231A(VisaInstrument):
    """Boonton 4231A RF Power Meter (legacy, non-SCPI)."""

    IDN_KEYWORDS = ("4231", "BOONTON")
    MODEL_NAME = "Boonton 4231A"
    SUPPORTS_SCPI_ERR_QUEUE = False

    # ---- Tập lệnh PLACEHOLDER — TODO(hardware): thay theo manual 4231A ----
    CMD_IDN = "*IDN?"        # TODO(hardware): nhiều khả năng KHÔNG hỗ trợ
    CMD_TRIGGER = "TR"       # TODO(hardware): mã trigger giả định
    CMD_READ = "TR"          # TODO(hardware): cách lấy kết quả (có thể chỉ cần read)
    CMD_FREQ_FMT = "FR {val} HZ"   # TODO(hardware): cú pháp đặt tần số cal factor
    CMD_UNIT_DBM = "DM"      # TODO(hardware): chọn đơn vị dBm
    CMD_ZERO = "ZE"          # TODO(hardware): lệnh zero đầu đo
    # ----------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        self._cal_freq_hz = 50.0e6
        self._mock_power_dbm = -20.0
        kwargs.setdefault("strict_idn", False)
        super().__init__(*args, **kwargs)

    # --- Nhận diện (fallback) ----------------------------------------
    def identify(self) -> str:
        try:
            resp = self._query(self.CMD_IDN)
            if resp and resp != "0":
                return resp
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: *IDN? không khả dụng (%s).", self.MODEL_NAME, exc)
        return "Boonton,4231A,UNKNOWN,(no *IDN?)"

    # --- CONTROL -----------------------------------------------------
    def set_frequency(self, freq_hz: float) -> None:
        """Đặt tần số tín hiệu để máy áp đúng cal factor đầu đo."""
        if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
            raise ValueError(
                f"freq {freq_hz} Hz ngoài dải [{FREQ_MIN_HZ}..{FREQ_MAX_HZ}] Hz"
            )
        self._write(self.CMD_FREQ_FMT.format(val=f"{freq_hz:.0f}"))
        self._cal_freq_hz = freq_hz
        logger.info("%s: cal freq = %.6f MHz (best-effort)",
                    self.MODEL_NAME, freq_hz / 1e6)

    def zero(self) -> None:
        """Zero đầu đo (đầu vào phải không có tín hiệu). TODO(hardware)."""
        self._write(self.CMD_ZERO)
        logger.info("%s: zero (best-effort).", self.MODEL_NAME)

    # --- ACQUIRE -----------------------------------------------------
    def measure_power(self) -> Reading:
        """Kích hoạt và đọc công suất (dBm)."""
        raw = self._query(self.CMD_READ, timeout_override_ms=15000)
        value = self._parse_boonton_power(raw)
        return Reading(value=value, unit="dBm", raw=raw)

    def _parse_boonton_power(self, raw: str) -> float:
        """
        Parse kết quả Boonton. TODO(hardware): máy đời cũ có thể trả chuỗi kèm
        header/đơn vị (vd 'DM -20.05' hoặc '-2.005E+01'). Hiện bóc số float đầu.
        """
        for t in raw.strip().replace(",", " ").split():
            try:
                return float(t)
            except ValueError:
                continue
        try:
            return float(raw.strip().lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ "))
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được công suất: '{raw}'"
            ) from exc

    def get_status(self) -> dict:
        st = super().get_status()
        st["cal_freq_hz"] = self._cal_freq_hz
        st["note"] = "legacy non-SCPI; lệnh là best-effort (xem TODO)."
        return st

    # --- Mock --------------------------------------------------------
    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if cmd.strip() in (self.CMD_READ, self.CMD_TRIGGER) or "POW" in cmd.upper():
            import random
            return f"DM {self._mock_power_dbm + random.gauss(0, 0.03):.3f}"
        return "0"

    def _mock_idn(self) -> str:
        return "BOONTON,4231A,00000001,REV1.0"
