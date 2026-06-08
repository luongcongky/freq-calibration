"""
drivers/keysight_power.py
=========================
Driver cho nhóm máy đo công suất cao tần Keysight (EPM / P-series):
    - E4410A   (power meter dòng EPM)
    - N1911A   (P-series, 1 kênh)
    - N1913A   (EPM-series, 1 kênh)
    - N1914A   (EPM-series, 2 kênh)

3 thao tác giai đoạn 1:
    1. connect + *IDN?
    2. CONTROL  -> set_frequency()  (đặt tần số để máy chọn đúng cal factor)
       (kèm zero() tiện ích)
    3. ACQUIRE  -> measure_power()  (đọc công suất, đơn vị dBm)

Tham chiếu: Keysight EPM/P-Series Power Meters Programming Guide.
  - Đơn vị      : UNIT:POWer DBM
  - Tần số      : [:SENSe]:FREQuency <Hz>
  - Zero sensor : CALibration:ZERO:AUTO ONCE
  - Đọc         : READ? / FETCh? / MEASure:POWer:AC?
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

FREQ_MIN_HZ = 1.0e3
FREQ_MAX_HZ = 110.0e9


class _KeysightPowerMeter(VisaInstrument):
    """Phần chung dòng power meter Keysight (helper trong-file)."""

    DEFAULT_CHANNELS = 1

    def __init__(self, *args, **kwargs):
        self._cal_freq_hz = 50.0e6   # 50 MHz mặc định
        self._mock_power_dbm = -10.0
        super().__init__(*args, **kwargs)

    # --- CONTROL -----------------------------------------------------
    def set_frequency(self, freq_hz: float, channel: int = 1) -> None:
        """Đặt tần số tín hiệu để máy áp đúng cal factor của đầu đo."""
        if not (FREQ_MIN_HZ <= freq_hz <= FREQ_MAX_HZ):
            raise ValueError(
                f"freq {freq_hz} Hz ngoài dải [{FREQ_MIN_HZ}..{FREQ_MAX_HZ}] Hz"
            )
        self._write(f"SENS{channel}:FREQ {freq_hz:.6f}")
        self._cal_freq_hz = freq_hz
        logger.info("%s: cal freq CH%d = %.6f MHz",
                    self.MODEL_NAME, channel, freq_hz / 1e6)

    def get_frequency(self, channel: int = 1) -> float:
        return float(self._query(f"SENS{channel}:FREQ?"))

    def set_unit_dbm(self, channel: int = 1) -> None:
        """Đặt đơn vị đọc về dBm."""
        self._write(f"UNIT{channel}:POW DBM")

    def zero(self, channel: int = 1) -> None:
        """Zero đầu đo (auto-zero một lần). Đầu vào phải không có tín hiệu."""
        self._write(f"CAL{channel}:ZERO:AUTO ONCE")
        self.wait_for_completion(timeout_s=30.0)
        logger.info("%s: zero CH%d hoàn tất.", self.MODEL_NAME, channel)

    # --- ACQUIRE -----------------------------------------------------
    def measure_power(self, channel: int = 1) -> Reading:
        """Đọc công suất hiện tại (dBm)."""
        raw = self._query(f"FETC{channel}?", timeout_override_ms=15000)
        try:
            return Reading(value=float(raw), unit="dBm", channel=channel, raw=raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được công suất: '{raw}'"
            ) from exc

    def get_status(self) -> dict:
        st = super().get_status()
        st["cal_freq_hz"] = self._cal_freq_hz
        st["channels"] = self.DEFAULT_CHANNELS
        return st

    # --- Mock --------------------------------------------------------
    def _mock_write(self, cmd: str) -> None:
        if "FREQ" in cmd and "?" not in cmd:
            try:
                self._cal_freq_hz = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if "FETC" in cmd or "READ" in cmd or "MEAS" in cmd:
            import random
            return f"{self._mock_power_dbm + random.gauss(0, 0.02):.4f}"
        if "FREQ?" in cmd:
            return f"{self._cal_freq_hz:.6f}"
        return super()._mock_response(cmd)


class E4410A(_KeysightPowerMeter):
    """Keysight E4410A RF Power Meter (dòng EPM)."""
    IDN_KEYWORDS = ("E4410A",)
    MODEL_NAME = "Keysight E4410A"

    def _mock_idn(self) -> str:
        return "Agilent Technologies,E4410A,GB00000001,A1.00.00"


class N1911A(_KeysightPowerMeter):
    """Keysight N1911A P-Series Power Meter (1 kênh)."""
    IDN_KEYWORDS = ("N1911A",)
    MODEL_NAME = "Keysight N1911A"

    def _mock_idn(self) -> str:
        return "Agilent Technologies,N1911A,MY00000001,A2.01.06"


class N1913A(_KeysightPowerMeter):
    """Keysight N1913A EPM-Series Power Meter (1 kênh)."""
    IDN_KEYWORDS = ("N1913A",)
    MODEL_NAME = "Keysight N1913A"

    def _mock_idn(self) -> str:
        return "Keysight Technologies,N1913A,MY00000002,A1.02.00"


class N1914A(_KeysightPowerMeter):
    """Keysight N1914A EPM-Series Power Meter (2 kênh)."""
    IDN_KEYWORDS = ("N1914A",)
    MODEL_NAME = "Keysight N1914A"
    DEFAULT_CHANNELS = 2

    def _mock_idn(self) -> str:
        return "Keysight Technologies,N1914A,MY00000003,A1.02.00"
