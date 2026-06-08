"""
drivers/fluke_counters.py
=========================
Driver cho nhóm máy đếm tần số cao tần/siêu cao tần Fluke/Philips:
    - PM 6680x   (PM6680 / PM6680B — Philips đời cũ, tập lệnh riêng)
    - PM 6690x   (PM6690 — Fluke, ≈ Pendulum CNT-90, SCPI đầy đủ)

Bối cảnh: dòng PM669x sau này thuộc Fluke/Pendulum nên cú pháp SCPI gần như
giống CNT-90. Dòng PM668x cũ hơn (Philips) dùng tập lệnh ASCII riêng.

3 thao tác giai đoạn 1:
    1. connect + *IDN?
    2. CONTROL  -> set_gate_time()
    3. ACQUIRE  -> measure_frequency()
"""

from __future__ import annotations

import logging

from .base_visa import VisaInstrument, Reading, MeasurementError

logger = logging.getLogger(__name__)

GATE_MIN_S = 1e-4
GATE_MAX_S = 1000.0


class PM6690(VisaInstrument):
    """
    Fluke PM6690 Frequency Counter/Analyzer (SCPI, ≈ Pendulum CNT-90).

    CONTROL : set_gate_time()  -> SENS:ACQ:APER
    ACQUIRE : measure_frequency() -> MEAS:FREQ? (@ch)
    """
    IDN_KEYWORDS = ("PM6690", "PM 6690")
    MODEL_NAME = "Fluke PM6690"
    DEFAULT_GATE_TIME_S = 1.0

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 1.0e8  # 100 MHz giả lập
        super().__init__(*args, **kwargs)

    def set_gate_time(self, gate_s: float) -> None:
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise ValueError(f"gate_time {gate_s}s ngoài dải hợp lệ")
        self._write(f"SENS:ACQ:APER {gate_s:.9f}")
        self._gate_time_s = gate_s
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s", self.MODEL_NAME, gate_s)

    def get_gate_time(self) -> float:
        return float(self._query("SENS:ACQ:APER?"))

    def measure_frequency(self, channel: int = 1) -> Reading:
        raw = self._query(
            f"MEAS:FREQ? (@{channel})",
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
            return f"{self._mock_freq + random.gauss(0, 0.4):.6f}"
        if "ACQ:APER?" in cmd:
            return f"{self._gate_time_s:.9f}"
        return super()._mock_response(cmd)

    def _mock_idn(self) -> str:
        return "Fluke,PM6690,901234,V1.30"


class PM6680(VisaInstrument):
    """
    Philips/Fluke PM6680 / PM6680B Frequency Counter (đời cũ).

    TODO(hardware): PM6680B dùng tập lệnh ASCII riêng của Philips (không phải
    SCPI chuẩn). Ví dụ một số máy nhận:
        "FREQ A"      -> chọn hàm đo tần số kênh A
        "MEAS?"/"X"   -> kích hoạt & đọc kết quả
        "TA <s>"      -> đặt measurement time
    Mã dưới đây triển khai theo cú pháp SCPI best-effort + có alias để dễ chỉnh.
    Cần đối chiếu PM6680B Programming Manual khi chạy máy thật.
    """
    IDN_KEYWORDS = ("PM6680", "PM 6680")
    MODEL_NAME = "Philips/Fluke PM6680"
    DEFAULT_GATE_TIME_S = 1.0

    # Cờ cho phép sau này chuyển sang tập lệnh Philips cổ điển nếu cần.
    USE_LEGACY_SYNTAX = False

    def __init__(self, *args, **kwargs):
        self._gate_time_s = self.DEFAULT_GATE_TIME_S
        self._mock_freq = 5.0e7  # 50 MHz giả lập
        super().__init__(*args, **kwargs)

    def set_gate_time(self, gate_s: float) -> None:
        if not (GATE_MIN_S <= gate_s <= GATE_MAX_S):
            raise ValueError(f"gate_time {gate_s}s ngoài dải hợp lệ")
        if self.USE_LEGACY_SYNTAX:
            self._write(f"TA {gate_s:.6f}")          # TODO(hardware): xác nhận
        else:
            self._write(f"SENS:ACQ:APER {gate_s:.9f}")
        self._gate_time_s = gate_s
        self.set_timeout(int(gate_s * 1000) + 5000)
        logger.info("%s: gate time = %.6f s", self.MODEL_NAME, gate_s)

    def get_gate_time(self) -> float:
        return float(self._query("SENS:ACQ:APER?"))

    def measure_frequency(self, channel: int = 1) -> Reading:
        if self.USE_LEGACY_SYNTAX:
            self._write("FREQ A")                    # TODO(hardware): xác nhận
            raw = self._query("X")
        else:
            raw = self._query(
                f"MEAS:FREQ? (@{channel})",
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

    def _mock_write(self, cmd: str) -> None:
        if "ACQ:APER" in cmd and "?" not in cmd:
            try:
                self._gate_time_s = float(cmd.split()[-1])
            except (ValueError, IndexError):
                pass

    def _mock_response(self, cmd: str) -> str:
        if "*IDN?" in cmd:
            return self._mock_idn()
        if "MEAS:FREQ?" in cmd or cmd.strip() == "X":
            import random
            return f"{self._mock_freq + random.gauss(0, 0.6):.6f}"
        if "ACQ:APER?" in cmd:
            return f"{self._gate_time_s:.9f}"
        return super()._mock_response(cmd)

    def _mock_idn(self) -> str:
        return "Philips,PM6680B,567890,V3.0"
