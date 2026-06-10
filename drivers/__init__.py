"""
drivers/__init__.py
Gói driver thiết bị cho hệ thống kiểm định/hiệu chuẩn tần số & công suất.

Ngoài 2 driver gốc (SMW200A, CNT90XL), gói này còn export các driver mới cho
nhóm máy đếm tần số và nhóm máy đo công suất, cùng DEVICE_REGISTRY — bảng tra
cứu (category, class) dùng cho test parametrize và GUI tạo kịch bản sau này.
"""

from .base_visa import (
    VisaInstrument, Reading,
    InstrumentError, ConnectionError_, CommandError,
    MeasurementError, IdentificationError,
)

# --- Driver gốc / Signal Generator -----------------------------------------
from .smw200a import SMW200A, SMW200AError, SMW200AConnectionError
from .cnt90xl import (
    CNT90XL, CNT90XLError, CNT90XLConnectionError,
    MeasurementResult, StatisticsResult,
)

# --- Máy đếm tần số --------------------------------------------------------
from .pendulum_counters import CNT85, CNT90, CNT91
from .keysight_counters import (
    KS53131A, KS53132A, KS53220A, KS53150A, KS53151A, KS53147A,
)
from .fluke_counters import PM6680, PM6690
from .advantest_r5372p import AdvantestR5372P

# --- Máy đo công suất ------------------------------------------------------
from .keysight_power import E4410A, E4418A, N1911A, N1913A, N1914A
from .boonton_4231a import Boonton4231A
from .rs_nrvd import RSNRVD


# Phân loại: "counter" = máy đếm tần số, "power" = máy đo công suất.
# Ghi chú: driver cũ CNT90XL (drivers/cnt90xl.py) GIÀU tính năng nhưng dùng API
# riêng (MeasurementResult, không kế thừa VisaInstrument) và đã có test riêng ở
# test_connectivity.py. Nó KHÔNG nằm trong registry API-thống-nhất này; dòng
# CNT-90/90XL được class CNT90 (API mới) bao phủ ở đây.
DEVICE_REGISTRY: dict[str, dict] = {
    # ---- Signal generators ----
    "SMW200A":  {"category": "generator", "cls": SMW200A,  "vendor": "Rohde&Schwarz"},
    # ---- Frequency counters ----
    "CNT85":    {"category": "counter", "cls": CNT85,    "vendor": "Pendulum"},
    "CNT90":    {"category": "counter", "cls": CNT90,    "vendor": "Pendulum"},
    "CNT91":    {"category": "counter", "cls": CNT91,    "vendor": "Pendulum"},
    "53131A":   {"category": "counter", "cls": KS53131A, "vendor": "Keysight"},
    "53132A":   {"category": "counter", "cls": KS53132A, "vendor": "Keysight"},
    "53220A":   {"category": "counter", "cls": KS53220A, "vendor": "Keysight"},
    "53150A":   {"category": "counter", "cls": KS53150A, "vendor": "Keysight"},
    "53151A":   {"category": "counter", "cls": KS53151A, "vendor": "Keysight"},
    "53147A":   {"category": "counter", "cls": KS53147A, "vendor": "Keysight"},
    "PM6680":   {"category": "counter", "cls": PM6680,   "vendor": "Fluke/Philips"},
    "PM6690":   {"category": "counter", "cls": PM6690,   "vendor": "Fluke"},
    "R5372P":   {"category": "counter", "cls": AdvantestR5372P, "vendor": "Advantest"},
    # ---- Power meters ----
    "E4410A":   {"category": "power", "cls": E4410A,  "vendor": "Keysight"},
    "E4418A":   {"category": "power", "cls": E4418A,  "vendor": "Keysight"},
    "N1911A":   {"category": "power", "cls": N1911A,  "vendor": "Keysight"},
    "N1913A":   {"category": "power", "cls": N1913A,  "vendor": "Keysight"},
    "N1914A":   {"category": "power", "cls": N1914A,  "vendor": "Keysight"},
    "4231A":    {"category": "power", "cls": Boonton4231A, "vendor": "Boonton"},
    "NRVD":     {"category": "power", "cls": RSNRVD,      "vendor": "Rohde&Schwarz"},
}


__all__ = [
    # base
    "VisaInstrument", "Reading",
    "InstrumentError", "ConnectionError_", "CommandError",
    "MeasurementError", "IdentificationError",
    # gốc
    "SMW200A", "SMW200AError", "SMW200AConnectionError",
    "CNT90XL", "CNT90XLError", "CNT90XLConnectionError",
    "MeasurementResult", "StatisticsResult",
    # counters
    "CNT85", "CNT90", "CNT91",
    "KS53131A", "KS53132A", "KS53220A", "KS53150A", "KS53151A", "KS53147A",
    "PM6680", "PM6690", "AdvantestR5372P",
    # power
    "E4410A", "E4418A", "N1911A", "N1913A", "N1914A", "Boonton4231A", "RSNRVD",
    # registry
    "DEVICE_REGISTRY",
]