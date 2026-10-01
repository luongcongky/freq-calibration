"""
drivers/generic.py
===================
Driver "rỗng" cho thiết bị VISA chưa có driver chuyên biệt — dùng khi người
dùng tự thêm 1 dòng máy mới (xem core/custom_devices.py) và chỉ cần gửi lệnh
SCPI thô (Command Reference / bước "raw_scpi" trong kịch bản), không cần phần
mềm tự đo/tính theo cấu trúc riêng của máy như các driver chuyên biệt khác
(measure_frequency, set_rf_power, ...).

KHÔNG override _mock_response/_mock_idn gì thêm — hành vi mock mặc định của
VisaInstrument (trả '0' cho mọi lệnh, *IDN? giả theo MODEL_NAME) đã đủ để
soạn/thử kịch bản offline trước khi có máy thật.
"""

from __future__ import annotations

from .base_visa import VisaInstrument


class GenericVisaInstrument(VisaInstrument):
    """Lớp nền cho driver 'generic'. core/custom_devices.py tạo 1 class con
    RỖNG cho MỖI dòng máy người dùng tự thêm, gắn MODEL_NAME/IDN_KEYWORDS
    tương ứng — y hệt cách mỗi driver chuyên biệt tự khai 2 thuộc tính này."""
    MODEL_NAME = "Generic VISA Instrument"
    IDN_KEYWORDS: tuple[str, ...] = ()
