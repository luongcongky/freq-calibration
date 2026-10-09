"""
unit_test/test_device_manager.py
===================================
Test gui/device_manager.py::DeviceManagerDialog — các sửa lỗi phát hiện ở
BUG-21 (test_reports/2026-10-01_regression/BAO_CAO_TEST_LAI.md):

  - Badge "*IDN?" hiện "OK" xanh cho thiết bị nạp từ profile ĐÃ LƯU (phiên
    trước), dù CHƯA kiểm tra lại máy có còn trả lời hay không -> hiểu lầm
    là đã xác nhận kết nối. Giờ phải hiện "Đã lưu" (trung tính), không phải
    "OK" (chỉ dành cho vừa quét/test THẬT xong).
  - Nút "Scan & Identify" hiện đúng 1 dấu & (trước đây Qt coi là phím tắt,
    hiện thành "Scan  Identify"/"Scan _Identify").
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel

from core.profile import ConnectionProfile, ProfileEntry
from gui.device_manager import DeviceManagerDialog, _COL_IDN

_app = QApplication.instance() or QApplication([])


def _idn_badge_text(dlg: DeviceManagerDialog, row: int) -> str:
    w = dlg.table.cellWidget(row, _COL_IDN)
    lbl = w.findChild(QLabel)
    return lbl.text()


def test_profile_loaded_idn_shows_saved_not_ok():
    profile = ConnectionProfile(entries=[
        ProfileEntry(model_key="CNT90", address="GPIB1::10::INSTR",
                     idn="Pendulum,CNT-90,SN1,1.0"),
    ])
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=profile)
    try:
        assert dlg.table.rowCount() == 1
        assert _idn_badge_text(dlg, 0) == "Đã lưu"
    finally:
        dlg.deleteLater()


def test_live_scan_row_still_shows_ok():
    """Hàng dựng từ quét THẬT (không qua _load_profile_into_table) vẫn hiện
    "OK" như cũ — chỉ đường nạp từ profile mới đổi thành "Đã lưu"."""
    from core.discovery import DiscoveredDevice

    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        dev = DiscoveredDevice(address="GPIB0::13::INSTR", idn="Boonton,4231A,SN2,1.0")
        dlg._add_row(dev)
        assert _idn_badge_text(dlg, 0) == "OK"
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# K05 (test_reports/2026-10-09_khong_thiet_bi/BAO_CAO_TEST_KHONG_THIET_BI.md):
# "Test" cả 3 dòng đều thất bại, bấm "Xác nhận" vẫn không hỏi gì -> hiện
# chấm xanh "đã kết nối" như bình thường ở mọi nơi khác trong app.
# ---------------------------------------------------------------------------

def test_accept_warns_when_a_tested_row_failed(monkeypatch):
    from core.discovery import DiscoveredDevice, ConnectionTest
    from gui import device_manager as dm_mod

    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        dev = DiscoveredDevice(address="GPIB0::28::INSTR", idn="")
        dlg._add_row(dev, assign="SMW200A")
        monkeypatch.setattr(dm_mod, "test_connection",
                            lambda model_key, address, mock=False:
                                ConnectionTest(ok=False, error="timeout"))
        dlg._test_row(0)
        assert dlg._test_ok[0] is False

        asked = {}
        monkeypatch.setattr(dm_mod, "confirm_yes_no",
                            lambda *a, **k: (asked.update(title=a[1]), False)[1])
        dlg._on_accept()
        assert "Test thất bại" in asked.get("title", ""), (
            f"Không cảnh báo khi Xác nhận dù Test thất bại (K05): {asked}")
    finally:
        dlg.deleteLater()


def test_accept_does_not_warn_when_tests_pass(monkeypatch):
    from core.discovery import DiscoveredDevice, ConnectionTest
    from gui import device_manager as dm_mod

    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        dev = DiscoveredDevice(address="GPIB0::13::INSTR", idn="")
        dlg._add_row(dev, assign="4231A")
        monkeypatch.setattr(dm_mod, "test_connection",
                            lambda model_key, address, mock=False:
                                ConnectionTest(ok=True, model="4231A"))
        dlg._test_row(0)

        asked = {"called": False}
        monkeypatch.setattr(dm_mod, "confirm_yes_no",
                            lambda *a, **k: asked.update(called=True) or False)
        dlg._on_accept()
        assert asked["called"] is False, "Cảnh báo Test thất bại dù Test đã OK"
    finally:
        dlg.deleteLater()


def test_clear_rows_resets_test_ok_tracking():
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        dlg._test_ok[0] = False
        dlg._clear_rows()
        assert dlg._test_ok == {}
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# K02 (test_reports/2026-10-09_khong_thiet_bi/BAO_CAO_TEST_KHONG_THIET_BI.md):
# Scan ra 0 thiết bị (máy tắt) trước đây vẫn xóa sạch các dòng profile đã
# nạp mà không hỏi, rồi báo "✅ Scan hoàn tất" xanh như quét thành công.
# ---------------------------------------------------------------------------

def test_scan_done_with_no_devices_keeps_existing_rows_and_warns():
    from core.discovery import DiscoveredDevice

    profile = ConnectionProfile(entries=[
        ProfileEntry(model_key="CNT90", address="GPIB0::13::INSTR",
                     idn="Boonton,4231A,SN1,1.0"),
    ])
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=profile)
    try:
        assert dlg.table.rowCount() == 1

        # Máy tắt -> VISA vẫn thấy địa chỉ nhưng *IDN? rỗng/lỗi (không phải
        # list trống hẳn, nhưng is_matched/idn đều rỗng).
        dlg._on_scan_done([DiscoveredDevice(address="GPIB0::13::INSTR", idn="",
                                            error="timeout")])

        assert dlg.table.rowCount() == 1, (
            "Scan 0 thiết bị đã xóa mất các dòng profile cũ (K02)")
        assert "Không tìm thấy" in dlg.lbl_status.text()
    finally:
        dlg.deleteLater()


def test_scan_done_with_devices_still_replaces_rows_as_before():
    """Không được vô tình đổi hành vi khi quét THẬT thấy máy — vẫn thay
    bảng + báo xanh "Scan hoàn tất" như cũ."""
    from core.discovery import DiscoveredDevice

    profile = ConnectionProfile(entries=[
        ProfileEntry(model_key="CNT90", address="GPIB0::99::INSTR",
                     idn="Cu,CU,SN,1"),
    ])
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=profile)
    try:
        dlg._on_scan_done([DiscoveredDevice(address="GPIB0::13::INSTR",
                                            idn="Boonton,4231A,SN1,1.0")])
        assert dlg.table.rowCount() == 1
        assert "Scan hoàn tất" in dlg.lbl_status.text()
    finally:
        dlg.deleteLater()


def test_status_label_word_wraps_long_error_text():
    """K04: lỗi kết nối dài (VI_ERROR_BERR...) trước đây chỉ đọc được qua
    tooltip khi rê chuột, cột Trạng thái cắt mất chữ."""
    from core.discovery import DiscoveredDevice

    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        dlg._add_row(DiscoveredDevice(address="GPIB0::28::INSTR", idn=""), assign="SMW200A")
        from gui.device_manager import _COL_STATUS
        w = dlg.table.cellWidget(0, _COL_STATUS)
        lbl = w.findChild(QLabel)
        assert lbl.wordWrap() is True
    finally:
        dlg.deleteLater()


def test_scan_button_label_has_literal_ampersand():
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        assert dlg.btn_scan.text() == "🔍 Scan && Identify"
    finally:
        dlg.deleteLater()
