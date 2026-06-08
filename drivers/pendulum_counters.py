"""
drivers/pendulum_counters.py
============================
Driver cho nhóm máy đếm tần số Pendulum:
    - CNT-85        (đời cũ hơn, best-effort)
    - CNT-90        (≈ CNT-90XL, SCPI đầy đủ)
    - CNT-91        (SCPI đầy đủ, throughput cao)

Lưu ý: CNT-90XL đã có driver riêng tại drivers/cnt90xl.py (giàu tính năng).
Các class ở đây tập trung vào 3 thao tác cốt lõi mà giai đoạn 1 yêu cầu:
    1. connect + nhận diện model (*IDN?)
    2. MỘT lệnh điều khiển  -> set_gate_time()
    3. MỘT lệnh thu thập     -> measure_frequency()

Tập lệnh SCPI tham chiếu: Pendulum CNT-90/91 Programmer's Guide.
  - Gate/measurement time : [:SENSe]:ACQuisition:APERture <seconds>
  - Đo tần số             : MEASure:FREQuency? (@<ch>)
  - Reference clock       : :SENSe:ROSCillator:SOURce INT|EXT
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

# Dải gate time hợp lệ (giây) — dùng để validate đầu vào tại driver.
GATE_MIN_S = 1e-4
GATE_MAX_S = 1000.0


class _PendulumCounter(VisaInstrument):
    """
    Phần dùng chung cho dòng Pendulum (chỉ là helper trong-file, KHÔNG phải
    driver-generic). Mỗi model cụ thể vẫn là class riêng bên dưới, khai báo
    IDN/model và (nếu cần) override lệnh đặc thù của mình.
    """

    DEFAULT_GATE_TIME_S = 1.0

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 1.0e7  # 10 MHz giả lập
        super().__init__(*args, **kwargs)

    # --- CONTROL: 1 lệnh điều khiển ----------------------------------
    def set_gate_time(self, gate_s: float) -> None:
        """Đặt thời gian gate/aperture (giây). Gate dài hơn => phân giải cao hơn."""
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise ValueError(
                f"gate_time {gate_s}s ngoài dải [{GATE_MIN_S}..{GATE_MAX_S}]s"
            )
        self._write(f"SENS:ACQ:APER {gate_s:.9f}")
        self._gate_time_s = gate_s
        # Gate dài thì nới timeout I/O để tránh VisaIOError.
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s", self.MODEL_NAME, gate_s)

    def get_gate_time(self) -> float:
        """Đọc lại gate time hiện hành (giây)."""
        return float(self._query("SENS:ACQ:APER?"))

    # --- ACQUIRE: 1 lệnh thu thập ------------------------------------
    def measure_frequency(self, channel: int = 1) -> Reading:
        """Đo tần số một lần trên kênh chỉ định, trả Reading (Hz)."""
        raw = self._query(
            f"MEAS:FREQ? (@{channel})",
            timeout_override_ms=int(self._gate_time_s * 1000) + 5000,
        )
        try:
            value = float(raw)
        except ValueError as exc:
            raise MeasurementError(
                f"{self.MODEL_NAME}: không parse được tần số: '{raw}'"
            ) from exc
        return Reading(value=value, unit="Hz", channel=channel, raw=raw)

    # --- Reference clock (tiện ích) ----------------------------------
    def set_reference_external(self, freq_hz: float = 10e6) -> None:
        """Khóa vào chuẩn ngoài 10 MHz."""
        self._write("SENS:ROSC:SOUR EXT")
        self._write(f"SENS:ROSC:EXT:FREQ {freq_hz:.0f}")
        logger.info("%s: reference EXTERNAL %.0f Hz", self.MODEL_NAME, freq_hz)

    def get_status(self) -> dict:
        st = super().get_status()
        st["gate_time_s"] = self._gate_time_s
        return st

    # --- Mock --------------------------------------------------------
    def _mock_write(self, cmd: str) -> None:
        if "ACQ:APER" in cmd and "?" not in cmd:
            try:
                self._gate_time_s = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if "MEAS:FREQ?" in cmd or "READ:FREQ?" in cmd:
            import random
            return f"{self._mock_freq + random.gauss(0, 0.5):.6f}"
        if "ACQ:APER?" in cmd:
            return f"{self._gate_time_s:.9f}"
        if "ROSC:SOUR?" in cmd:
            return "INT"
        return super()._mock_response(cmd)


class CNT85(_PendulumCounter):
    """
    Pendulum CNT-85 — máy đếm tần số đời cũ hơn dòng CNT-90.

    TODO(hardware): CNT-85 có thể dùng cú pháp SCPI hơi khác dòng CNT-90
    (đặc biệt lệnh gate). Cần đối chiếu Programmer's Guide CNT-85 khi chạy máy
    thật; mã hiện tại theo cú pháp CNT-90 (best-effort).
    """
    IDN_KEYWORDS = ("CNT-85", "CNT85")
    MODEL_NAME = "Pendulum CNT-85"

    def _mock_idn(self) -> str:
        return "Pendulum Instruments,CNT-85,123456,V1.20"


class CNT90(_PendulumCounter):
    """Pendulum CNT-90 — máy đếm tần số cao tần (≈ CNT-90XL), SCPI đầy đủ."""
    IDN_KEYWORDS = ("CNT-90", "CNT90")
    MODEL_NAME = "Pendulum CNT-90"

    def _mock_idn(self) -> str:
        return "Pendulum Instruments,CNT-90,654321,V2.10"


class CNT91(_PendulumCounter):
    """Pendulum CNT-91 — máy đếm tần số throughput cao, SCPI đầy đủ."""
    IDN_KEYWORDS = ("CNT-91", "CNT91")
    MODEL_NAME = "Pendulum CNT-91"

    def _mock_idn(self) -> str:
        return "Pendulum Instruments,CNT-91,789012,V2.10"
