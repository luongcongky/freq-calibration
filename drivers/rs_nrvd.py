"""
drivers/rs_nrvd.py
==================
Driver cho máy đo công suất cao tần Rohde & Schwarz NRVD.

IDN thực tế (GPIB0::21::INSTR):
    ROHDE&SCHWARZ,NRVD, 101692.002,V1.52  V1.40

NRVD là power meter 2 kênh đời cũ, hỗ trợ SCPI cơ bản IEEE-488.2.
Tập lệnh tham chiếu: R&S NRVD Operating Manual, Chapter 5 (Remote Control).

3 thao tác giai đoạn 1:
    1. connect + *IDN?
    2. CONTROL  -> set_frequency()  (đặt tần số để áp đúng cal factor)
    3. ACQUIRE  -> measure_power()  (đọc công suất, dBm)
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

FREQ_MIN_HZ = 1.0e3
FREQ_MAX_HZ = 26.5e9


class RSNRVD(VisaInstrument):
    """Rohde & Schwarz NRVD Dual-Channel Power Meter."""

    IDN_KEYWORDS = ("NRVD", "ROHDE&SCHWARZ,NRVD", "R&S,NRVD")
    MODEL_NAME = "R&S NRVD"

    # R&S NRVD dùng SCPI chuẩn, có error queue.
    CMD_IDN = "*IDN?"
    CMD_ERR = "SYST:ERR?"
    SUPPORTS_SCPI_ERR_QUEUE = True

    DEFAULT_TIMEOUT_MS = 15_000

    def __init__(self, *args, **kwargs):
        self._cal_freq_hz = 50.0e6
        self._mock_power_dbm = -10.0
        kwargs.setdefault("strict_idn", False)
        super().__init__(*args, **kwargs)
        self._set_unit_dbm_on_connect()

    # --- CONTROL --------------------------------------------------------

    def set_frequency(self, freq_hz: float, channel: int = 1) -> None:
        """Đặt tần số tín hiệu để máy áp đúng cal factor của đầu đo."""
        if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
            raise ValueError(
                f"freq {freq_hz} Hz ngoài dải [{FREQ_MIN_HZ}..{FREQ_MAX_HZ}] Hz"
            )
        self._write(f"SENS{channel}:FREQ {freq_hz:.0f}")
        self._cal_freq_hz = freq_hz
        logger.info("%s: cal freq CH%d = %.6f MHz",
                    self.MODEL_NAME, channel, freq_hz / 1e6)

    def get_frequency(self, channel: int = 1) -> float:
        return float(self._query(f"SENS{channel}:FREQ?"))

    def set_unit_dbm(self, channel: int = 1) -> None:
        """Đặt đơn vị đọc về dBm."""
        self._write(f"SENS{channel}:POW:UNIT DBM")

    def zero(self, channel: int = 1) -> None:
        """Zero đầu đo (đầu vào phải không có tín hiệu)."""
        self._write(f"CAL{channel}:ZERO:AUTO ONCE")
        self.wait_for_completion(timeout_s=30.0)
        logger.info("%s: zero CH%d hoàn tất.", self.MODEL_NAME, channel)

    # --- ACQUIRE --------------------------------------------------------

    # NRVD dùng MEAS? (không có số kênh) để trigger và đọc ngay.
    # READ? / READ1? bị timeout; FETC? trả sentinel 9.9E+37 khi chưa có đo mới.
    # UNIT:POW DBM được set trong connect() để cố định đơn vị trả về là dBm.
    _INVALID_SENTINEL = 9.9e37

    def _set_unit_dbm_on_connect(self) -> None:
        """Cố gắng đặt unit về dBm sau khi kết nối (best-effort, NRVD có thể bỏ qua)."""
        try:
            self._write("UNIT:POW DBM")
        except Exception:  # noqa: BLE001
            pass

    def measure_power(self, channel: int = 1) -> Reading:
        """Đọc công suất hiện tại (dBm). NRVD dùng MEAS? (không kèm số kênh)."""
        # channel bị bỏ qua trên NRVD — MEAS? luôn trả kết quả channel mặc định.
        raw = self._query("MEAS?", timeout_override_ms=20_000)
        try:
            value = float(raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được công suất: '{raw}'"
            ) from exc
        if value >= self._INVALID_SENTINEL:
            raise MeasurementError(
                f"{self.MODEL_NAME}: MEAS? trả sentinel không hợp lệ ({raw})"
            )
        return Reading(value=value, unit="dBm", channel=channel, raw=raw)

    def get_status(self) -> dict:
        st = super().get_status()
        st["cal_freq_hz"] = self._cal_freq_hz
        st["channels"] = 2
        return st

    # --- Mock -----------------------------------------------------------

    def _mock_write(self, cmd: str) -> None:
        if "FREQ" in cmd and "?" not in cmd:
            try:
                self._cal_freq_hz = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if cmd.strip() in ("MEAS?",) or "MEAS" in cmd:
            import random
            return f"{self._mock_power_dbm + random.gauss(0, 0.02):.4f}"
        if "FETC" in cmd:
            import random
            return f"{self._mock_power_dbm + random.gauss(0, 0.02):.4f}"
        if "FREQ?" in cmd:
            return f"{self._cal_freq_hz:.0f}"
        if "SYST:ERR" in cmd:
            return '0,"No error"'
        return "0"

    def _mock_idn(self) -> str:
        return "ROHDE&SCHWARZ,NRVD, 101692.002,V1.52  V1.40"
