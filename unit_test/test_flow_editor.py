"""
unit_test/test_flow_editor.py
================================
Test gui/flow_editor.py::FlowEditorWindow — R4-03 (test_reports/
2026-10-08_round4/BAO_CAO_TEST_VONG_4.md): chế độ Digital luôn chạy MOCK dù
danh sách thiết bị bên trái hiện "● đã kết nối" (devices không rỗng), vì
constructor KHÔNG nhận address_map thật từ theme Classic — self._address_map
hardcode rỗng, chỉ có giá trị thật nếu người dùng tự bấm lại Step 1 "Scan"
NGAY TRONG Digital, dù đã scan rồi ở Classic. FlowRunWorker tự rơi về mock
khi address_map rỗng (core/scenario_runner.py), không báo gì trên giao diện
-> hiện số liệu giả như số đo thật.
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication

from gui.flow_editor import FlowEditorWindow

_app = QApplication.instance() or QApplication([])

_DEVICES = [{"name": "4231A", "key": "4231A", "sub": "GPIB0::13::INSTR", "icon": "🔌"}]


def test_flow_editor_accepts_real_address_map_from_constructor():
    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False,
                           address_map={"4231A": "GPIB0::13::INSTR"}, cmd_delay_s=0.2)
    try:
        assert win._address_map == {"4231A": "GPIB0::13::INSTR"}
        assert win._cmd_delay_s == 0.2
        assert win._connected is True
    finally:
        win.deleteLater()


def test_flow_editor_defaults_to_empty_address_map_when_not_given():
    """Không truyền address_map (vd mở demo độc lập) -> vẫn rỗng như cũ,
    không crash — chỉ đổi hành vi khi CÓ truyền."""
    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        assert win._address_map == {}
    finally:
        win.deleteLater()


def test_switch_to_digital_passes_real_address_map(monkeypatch):
    """gui/scenario_grid.py::ScenarioGridWindow._switch_to_digital() phải
    mang theo address_map/cmd_delay_s THẬT đã có ở Classic sang Digital —
    trước đây không truyền gì cả, Digital luôn rơi về mock dù Classic đã
    kết nối thiết bị thật."""
    from gui.scenario_grid import ScenarioGridWindow

    win = ScenarioGridWindow(parent=None, address_map={"4231A": "GPIB0::13::INSTR"},
                             cmd_delay_s=0.3)
    try:
        monkeypatch.setattr(win, "hide", lambda: None)
        win._switch_to_digital()
        try:
            assert win._flow_win._address_map == {"4231A": "GPIB0::13::INSTR"}, (
                "Digital không nhận được address_map thật từ Classic (R4-03)")
            assert win._flow_win._cmd_delay_s == 0.3
        finally:
            win._flow_win.deleteLater()
    finally:
        win.deleteLater()


def test_do_run_warns_when_connected_but_address_map_empty(monkeypatch):
    """_connected=True (devices không rỗng) nhưng _address_map rỗng (lệch
    trạng thái) -> phải cảnh báo rõ "MÔ PHỎNG" trước khi chạy, không chạy
    thẳng ra số giả mà không nói gì (báo cáo lỗi R4-03)."""
    from gui import flow_editor as fe_mod

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        assert win._connected is True and win._address_map == {}

        asked = {}
        def fake_confirm(parent, title, text, default_yes=True):
            asked["title"] = title
            return False   # người dùng chọn Không -> KHÔNG được chạy

        monkeypatch.setattr(fe_mod, "confirm_yes_no", fake_confirm)
        win._do_run()

        assert "title" in asked, "Không cảnh báo MÔ PHỎNG dù address_map rỗng (R4-03)"
        assert win.worker is None, "Vẫn chạy mô phỏng dù người dùng chọn Không"
    finally:
        win.deleteLater()
