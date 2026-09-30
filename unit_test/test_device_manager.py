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


def test_scan_button_label_has_literal_ampersand():
    dlg = DeviceManagerDialog(parent=None, mock=True, profile=ConnectionProfile())
    try:
        assert dlg.btn_scan.text() == "🔍 Scan && Identify"
    finally:
        dlg.deleteLater()
