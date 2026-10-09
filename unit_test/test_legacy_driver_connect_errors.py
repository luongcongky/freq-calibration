"""
unit_test/test_legacy_driver_connect_errors.py
================================================
K04 (test_reports/2026-10-09_khong_thiet_bi/BAO_CAO_TEST_KHONG_THIET_BI.md):
thông báo lỗi kết nối không thống nhất ngôn ngữ — driver mới (dựa trên
drivers/base_visa.py) báo tiếng Việt "<máy>: không kết nối được tới
'<địa chỉ>': <lỗi>", nhưng 2 driver GỐC (SMW200A, CNT90XL, viết trước khi
có base_visa.py) báo tiếng Anh thuần "Cannot connect to <máy> at '<địa
chỉ>': <lỗi>".
"""

import pyvisa
import pytest


def _raise_visa_timeout(*a, **k):
    raise pyvisa.VisaIOError(-1073807339)   # VI_ERROR_TMO


def test_smw200a_connect_error_is_vietnamese(monkeypatch):
    from drivers.smw200a import SMW200A, SMW200AConnectionError

    monkeypatch.setattr(pyvisa, "ResourceManager",
                        lambda *a, **k: type("RM", (), {
                            "open_resource": staticmethod(_raise_visa_timeout),
                        })())
    with pytest.raises(SMW200AConnectionError) as exc_info:
        SMW200A("GPIB0::28::INSTR", mock=False)
    msg = str(exc_info.value)
    assert "không kết nối được tới" in msg, f"Vẫn báo tiếng Anh (K04): {msg!r}"
    assert "Cannot connect" not in msg


def test_cnt90xl_connect_error_is_vietnamese(monkeypatch):
    from drivers.cnt90xl import CNT90XL, CNT90XLConnectionError

    monkeypatch.setattr(pyvisa, "ResourceManager",
                        lambda *a, **k: type("RM", (), {
                            "open_resource": staticmethod(_raise_visa_timeout),
                        })())
    with pytest.raises(CNT90XLConnectionError) as exc_info:
        CNT90XL("GPIB0::13::INSTR", mock=False)
    msg = str(exc_info.value)
    assert "không kết nối được tới" in msg, f"Vẫn báo tiếng Anh (K04): {msg!r}"
    assert "Cannot connect" not in msg
