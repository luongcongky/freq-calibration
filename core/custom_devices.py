"""
core/custom_devices.py
=======================
Cho phép người dùng cuối tự thêm 1 "dòng máy" MỚI chưa có driver chuyên biệt,
ngay từ GUI (Quản lý thiết bị), không cần dev viết code + đóng gói lại bản
mới — với điều kiện họ chỉ cần gửi lệnh SCPI thô (bước "raw_scpi" trong kịch
bản / màn hình Tập lệnh thiết bị), không cần phần mềm tự đo/tính theo cấu
trúc riêng của máy (như measure_frequency, set_rf_power, ...) — những action
đó chỉ driver chuyên biệt (drivers/*.py) mới có.

Thiết kế:
  - Mọi dòng máy tự thêm đều chạy qua 1 class nền dùng chung:
    drivers.GenericVisaInstrument — chỉ lo phần kết nối VISA + gửi/nhận lệnh
    (thừa hưởng từ VisaInstrument), không có logic đo lường riêng.
  - get_device_registry() trả về DEVICE_REGISTRY gốc (hardcode trong
    drivers/__init__.py) GỘP với các dòng máy tự thêm đọc từ
    data/custom_devices.json — mỗi dòng máy tự thêm được tạo 1 class con RỖNG
    của GenericVisaInstrument (gắn MODEL_NAME/IDN_KEYWORDS theo đúng khai báo
    của người dùng), y hệt cách mỗi driver chuyên biệt tự khai 2 thuộc tính
    này (xem drivers/base_visa.py).
  - Mọi nơi trong app (GUI lẫn core) cần liệt kê/tra cứu dòng máy phải gọi
    get_device_registry() thay vì dùng thẳng DEVICE_REGISTRY, để luôn thấy cả
    2 nguồn (built-in + tự thêm).

Theo đúng mẫu đã có của data/custom_commands.json (core/commands.py): ghi
cạnh .exe khi đóng gói (PyInstaller), ghi ở gốc project khi chạy từ source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from drivers import DEVICE_REGISTRY, GenericVisaInstrument

if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent
CUSTOM_DEVICES_PATH = _BASE_DIR / "data" / "custom_devices.json"

CATEGORY_CHOICES = [
    ("counter", "Máy đếm tần số"),
    ("power", "Máy đo công suất"),
    ("generator", "Máy phát tín hiệu"),
    ("other", "Khác"),
]


def load_custom_devices() -> dict[str, dict]:
    if CUSTOM_DEVICES_PATH.exists():
        try:
            with open(CUSTOM_DEVICES_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_custom_devices(devices: dict[str, dict]) -> None:
    CUSTOM_DEVICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CUSTOM_DEVICES_PATH, "w", encoding="utf-8") as f:
        json.dump(devices, f, ensure_ascii=False, indent=2)


def _make_generic_class(model_key: str, label: str, idn_keywords: list[str]) -> type:
    """1 class con RỖNG của GenericVisaInstrument cho riêng model_key này —
    chỉ khai MODEL_NAME/IDN_KEYWORDS, không có logic đo lường (xem docstring
    module)."""
    return type(f"Generic_{model_key}", (GenericVisaInstrument,), {
        "MODEL_NAME": label or model_key,
        "IDN_KEYWORDS": tuple(idn_keywords),
    })


def get_device_registry() -> dict[str, dict]:
    """DEVICE_REGISTRY gốc (built-in) + mọi dòng máy người dùng tự thêm."""
    registry = dict(DEVICE_REGISTRY)
    for model_key, info in load_custom_devices().items():
        registry[model_key] = {
            "category": info.get("category", "other"),
            "cls": _make_generic_class(
                model_key, info.get("label", ""), info.get("idn_keywords", [])),
            "vendor": info.get("vendor", ""),
            "is_custom": True,
        }
    return registry


def validate_new_model_key(model_key: str) -> str:
    """Chuẩn hóa + kiểm tra model_key mới hợp lệ (chưa trùng built-in/custom).
    Trả model_key đã chuẩn hóa (viết hoa, khoảng trắng -> '_') hoặc raise
    ValueError kèm thông báo tiếng Việt."""
    key = model_key.strip().upper().replace(" ", "_")
    if not key:
        raise ValueError("Mã dòng máy không được để trống.")
    # str.isalnum() tính CẢ chữ có dấu (vd "Á", "Đ") là alnum (Unicode) nên
    # trước đây "Máy đo 1" lọt qua thành "MÁY_ĐO_1" dù placeholder ghi rõ
    # "không dấu" — gõ lại không dấu ("may do 1") tạo thêm "MAY_DO_1", ra 2
    # dòng gần trùng cho cùng 1 ý (báo cáo lỗi BUG-22). Chỉ cho A-Z/0-9/_
    # (ASCII thật) để thống nhất với hướng dẫn, không âm thầm nhận chữ có dấu.
    if not all(("A" <= c <= "Z") or ("0" <= c <= "9") or c == "_" for c in key):
        raise ValueError("Mã dòng máy chỉ gồm chữ KHÔNG DẤU (A-Z), số, dấu gạch dưới (_) "
                         "— không được có dấu tiếng Việt.")
    if key in DEVICE_REGISTRY:
        raise ValueError(f"Mã '{key}' đã là 1 dòng máy có sẵn trong phần mềm.")
    if key in load_custom_devices():
        raise ValueError(f"Mã '{key}' đã tồn tại trong danh sách tự thêm.")
    return key


def add_custom_device(model_key: str, label: str, vendor: str, category: str,
                       idn_keywords: list[str]) -> str:
    """Thêm 1 dòng máy mới, lưu ngay vào custom_devices.json. Trả model_key
    đã chuẩn hóa. Raise ValueError nếu model_key không hợp lệ/đã tồn tại."""
    key = validate_new_model_key(model_key)
    devices = load_custom_devices()
    devices[key] = {
        "label": label.strip(),
        "vendor": vendor.strip(),
        "category": category if category in dict(CATEGORY_CHOICES) else "other",
        "idn_keywords": [k.strip() for k in idn_keywords if k.strip()],
    }
    save_custom_devices(devices)
    return key


def remove_custom_device(model_key: str) -> None:
    devices = load_custom_devices()
    devices.pop(model_key, None)
    save_custom_devices(devices)


def is_custom_device(model_key: str) -> bool:
    return model_key in load_custom_devices()
