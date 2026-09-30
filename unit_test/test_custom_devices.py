"""
unit_test/test_custom_devices.py
===================================
Test core/custom_devices.py::validate_new_model_key()/add_custom_device() —
BUG-22 (test_reports/2026-10-01_regression/BAO_CAO_TEST_LAI.md): placeholder
ghi "(không dấu…)" nhưng "Máy đo 1" được lưu thành "MÁY_ĐO_1" (str.isalnum()
coi chữ có dấu là alnum), rồi "may do 1" tạo thêm "MAY_DO_1" -> 2 dòng gần
trùng cho cùng 1 ý.
"""

import pytest

from core import custom_devices


@pytest.fixture(autouse=True)
def _isolated_custom_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(custom_devices, "CUSTOM_DEVICES_PATH", tmp_path / "custom_devices.json")


def test_validate_new_model_key_normalizes_spaces_and_case():
    assert custom_devices.validate_new_model_key("may do a") == "MAY_DO_A"
    assert custom_devices.validate_new_model_key("  MAY_DO_B  ") == "MAY_DO_B"


def test_validate_new_model_key_rejects_vietnamese_diacritics():
    """Trước đây lọt qua thành "MÁY_ĐO_1" (str.isalnum() Unicode) — giờ phải
    báo lỗi rõ ràng, không âm thầm nhận chữ có dấu khác với placeholder."""
    with pytest.raises(ValueError, match="không dấu|KHÔNG DẤU"):
        custom_devices.validate_new_model_key("Máy đo 1")


def test_validate_new_model_key_rejects_empty():
    with pytest.raises(ValueError):
        custom_devices.validate_new_model_key("   ")


def test_validate_new_model_key_rejects_duplicate_builtin():
    builtin_key = next(iter(custom_devices.DEVICE_REGISTRY))
    with pytest.raises(ValueError, match="đã là"):
        custom_devices.validate_new_model_key(builtin_key)


def test_add_custom_device_then_validate_rejects_duplicate():
    custom_devices.add_custom_device("MAY_DO_1", "Máy đo 1", "ACME", "other", [])
    with pytest.raises(ValueError, match="đã tồn tại"):
        custom_devices.validate_new_model_key("may do 1")
