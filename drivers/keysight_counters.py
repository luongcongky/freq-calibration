"""
drivers/keysight_counters.py
============================
Driver cho nhóm máy đếm tần số Keysight/Agilent/HP:

  Universal counters (đo trực tiếp + gate time):
    - 53131A   (225 MHz / 3 GHz, 9-10 digit)
    - 53132A   (225 MHz / 3 GHz, 12 digit)
    - 53220A   (350 MHz universal counter)

  Microwave frequency counters (đầu vào cao tần/siêu cao tần, prescaler):
    - 53150A   (20 GHz CW counter)
    - 53151A   (26.5 GHz CW counter)
    - 53147A   (20 GHz counter + power meter + DVM)

Mỗi model là class riêng. Phần chung của từng dòng nằm ở:
    _KeysightUniversalCounter   (531x1A / 5322xA)
    _KeysightMicrowaveCounter   (5315xA / 53147A)

3 thao tác giai đoạn 1:
    1. connect + *IDN?
    2. CONTROL  -> set_gate_time()
    3. ACQUIRE  -> measure_frequency()

Tham chiếu: 53131A/132A Programming Guide, 53220A/230A SCPI Guide,
            53150-series Operating/Programming Manual.
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

GATE_MIN_S = 1e-3
GATE_MAX_S = 1000.0


# ===========================================================================
# Universal counters: 53131A / 53132A / 53220A
# ===========================================================================

class _KeysightUniversalCounter(VisaInstrument):
    """Phần chung dòng universal counter (helper trong-file, không generic)."""

    DEFAULT_GATE_TIME_S = 1.0
    # 53220A dùng SENS:FREQ:GATE:TIME; 53131A/132A dùng FREQ:ARM:STOP:TIM.
    # Mặc định theo 53220A; 53131A/132A override bên dưới.
    GATE_SET_CMD = "SENS:FREQ:GATE:TIME"
    GATE_GET_CMD = "SENS:FREQ:GATE:TIME?"

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 1.0e7
        super().__init__(*args, **kwargs)

    # --- CONTROL -----------------------------------------------------
    def set_gate_time(self, gate_s: float) -> None:
        """Đặt gate time (giây)."""
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise ValueError(f"gate_time {gate_s}s ngoài dải hợp lệ")
        self._write(f"{self.GATE_SET_CMD} {gate_s:.9f}")
        self._gate_time_s = gate_s
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s", self.MODEL_NAME, gate_s)

    def get_gate_time(self) -> float:
        return float(self._query(self.GATE_GET_CMD))

    # --- ACQUIRE -----------------------------------------------------
    def measure_frequency(self, channel: int = 1) -> Reading:
        """Đo tần số một lần, trả Reading (Hz)."""
        raw = self._query(
            f"MEAS:FREQ? (@{channel})",
            timeout_override_ms=int(self._gate_time_s * 1000) + 5000,
        )
        return self._parse_freq(raw, channel)

    def _parse_freq(self, raw: str, channel: int) -> Reading:
        try:
            return Reading(value=float(raw), unit="Hz", channel=channel, raw=raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được tần số: '{raw}'"
            ) from exc

    def get_status(self) -> dict:
        st = super().get_status()
        st["gate_time_s"] = self._gate_time_s
        return st

    # --- Mock --------------------------------------------------------
    def _mock_write(self, cmd: str) -> None:
        if "GATE:TIME" in cmd and "?" not in cmd:
            try:
                self._gate_time_s = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if "MEAS:FREQ?" in cmd or "READ:FREQ?" in cmd:
            import random
            return f"{self._mock_freq + random.gauss(0, 0.3):.6f}"
        if "GATE:TIME?" in cmd:
            return f"{self._gate_time_s:.9f}"
        return super()._mock_response(cmd)


class KS53131A(_KeysightUniversalCounter):
    """
    Keysight/HP 53131A Universal Counter.

    TODO(hardware): 53131A đặt gate qua khối ARM:
        :FREQ:ARM:STOP:SOUR TIM ; :FREQ:ARM:STOP:TIM <s>
    Đã override GATE_SET_CMD theo cú pháp này — cần xác nhận trên máy thật.
    """
    IDN_KEYWORDS = ("53131A",)
    MODEL_NAME = "Keysight 53131A"
    GATE_SET_CMD = "FREQ:ARM:STOP:TIM"
    GATE_GET_CMD = "FREQ:ARM:STOP:TIM?"

    def set_gate_time(self, gate_s: float) -> None:
        # 53131A cần chọn nguồn ARM là TIMer trước khi đặt giá trị.
        self._write("FREQ:ARM:STOP:SOUR TIM")
        super().set_gate_time(gate_s)

    def _mock_idn(self) -> str:
        return "HEWLETT-PACKARD,53131A,0,3944"


class KS53132A(_KeysightUniversalCounter):
    """Keysight/HP 53132A Universal Counter (12 digit)."""
    IDN_KEYWORDS = ("53132A",)
    MODEL_NAME = "Keysight 53132A"
    GATE_SET_CMD = "FREQ:ARM:STOP:TIM"
    GATE_GET_CMD = "FREQ:ARM:STOP:TIM?"

    def set_gate_time(self, gate_s: float) -> None:
        self._write("FREQ:ARM:STOP:SOUR TIM")
        super().set_gate_time(gate_s)

    def _mock_idn(self) -> str:
        return "HEWLETT-PACKARD,53132A,0,4806"


class KS53220A(_KeysightUniversalCounter):
    """Keysight 53220A 350 MHz Universal Counter (SCPI hiện đại)."""
    IDN_KEYWORDS = ("53220A",)
    MODEL_NAME = "Keysight 53220A"
    GATE_SET_CMD = "SENS:FREQ:GATE:TIME"
    GATE_GET_CMD = "SENS:FREQ:GATE:TIME?"

    def _mock_idn(self) -> str:
        return "Agilent Technologies,53220A,MY50000001,2.10"


# ===========================================================================
# Microwave frequency counters: 53150A / 53151A / 53147A
# ===========================================================================

class _KeysightMicrowaveCounter(VisaInstrument):
    """
    Phần chung dòng microwave CW counter (helper trong-file).

    TODO(hardware): dòng 5315x có tập lệnh đơn giản hơn universal counter và
    đôi khi đặt "resolution"/"sample time" thay vì gate time tường minh. Các
    lệnh dưới đây là best-effort theo SCPI chung — cần đối chiếu manual khi
    chạy máy thật.
    """

    DEFAULT_GATE_TIME_S = 1.0

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 1.0e10  # 10 GHz giả lập (siêu cao tần)
        super().__init__(*args, **kwargs)

    # --- CONTROL -----------------------------------------------------
    def set_gate_time(self, gate_s: float) -> None:
        """Đặt sample/gate time (giây)."""
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise ValueError(f"gate_time {gate_s}s ngoài dải hợp lệ")
        self._write(f"SENS:FREQ:GATE:TIME {gate_s:.9f}")
        self._gate_time_s = gate_s
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s", self.MODEL_NAME, gate_s)

    def get_gate_time(self) -> float:
        return float(self._query("SENS:FREQ:GATE:TIME?"))

    # --- ACQUIRE -----------------------------------------------------
    def measure_frequency(self, channel: int = 1) -> Reading:
        """Đo tần số CW cao tần một lần, trả Reading (Hz)."""
        raw = self._query(
            "MEAS:FREQ?",
            timeout_override_ms=int(self._gate_time_s * 1000) + 5000,
        )
        try:
            return Reading(value=float(raw), unit="Hz", channel=channel, raw=raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được tần số: '{raw}'"
            ) from exc

    def get_status(self) -> dict:
        st = super().get_status()
        st["gate_time_s"] = self._gate_time_s
        return st

    # --- Mock --------------------------------------------------------
    def _mock_write(self, cmd: str) -> None:
        if "GATE:TIME" in cmd and "?" not in cmd:
            try:
                self._gate_time_s = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if "MEAS:FREQ?" in cmd:
            import random
            return f"{self._mock_freq + random.gauss(0, 5):.3f}"
        if "GATE:TIME?" in cmd:
            return f"{self._gate_time_s:.9f}"
        if "MEAS:POW?" in cmd or "MEAS:SCAL:POW?" in cmd:
            import random
            return f"{-10.0 + random.gauss(0, 0.05):.3f}"
        return super()._mock_response(cmd)


class KS53150A(_KeysightMicrowaveCounter):
    """Keysight/HP 53150A CW Microwave Frequency Counter (20 GHz)."""
    IDN_KEYWORDS = ("53150A",)
    MODEL_NAME = "Keysight 53150A"

    def _mock_idn(self) -> str:
        return "HEWLETT-PACKARD,53150A,0,1.0"


class KS53151A(_KeysightMicrowaveCounter):
    """Keysight/HP 53151A CW Microwave Frequency Counter (26.5 GHz)."""
    IDN_KEYWORDS = ("53151A",)
    MODEL_NAME = "Keysight 53151A"

    def _mock_idn(self) -> str:
        return "HEWLETT-PACKARD,53151A,0,1.0"


class KS53147A(_KeysightMicrowaveCounter):
    """
    Keysight/HP 53147A — Microwave Counter (20 GHz) + Power Meter + DVM.

    Ngoài measure_frequency() còn có measure_power() do tích hợp đầu đo công suất.
    """
    IDN_KEYWORDS = ("53147A",)
    MODEL_NAME = "Keysight 53147A"

    def _mock_idn(self) -> str:
        return "HEWLETT-PACKARD,53147A,0,1.0"

    def measure_power(self) -> Reading:
        """Đo công suất cao tần tích hợp, trả Reading (dBm)."""
        raw = self._query("MEAS:SCAL:POW?")
        try:
            return Reading(value=float(raw), unit="dBm", raw=raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được công suất: '{raw}'"
            ) from exc
