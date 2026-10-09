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
from core.scenario_runner import StepResult

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


# ---------------------------------------------------------------------------
# K10 (test_reports/2026-10-09_khong_thiet_bi): ScenarioGridWindow mở từ
# Phiên Kiểm Định (chỉ truyền address_map, không truyền profile đầy đủ)
# -> self._profile không được gán -> _devices_for_flow() trả None ->
# Digital hiện "Chưa kết nối thiết bị / 0 Nodes" dù Classic đang ghi đúng
# số máy từ Phiên.
# ---------------------------------------------------------------------------

def test_switch_to_digital_shows_devices_even_without_explicit_profile(monkeypatch):
    """Phiên Kiểm Định trước đây chỉ truyền address_map (không có
    ConnectionProfile đầy đủ) -> self._profile không được gán -> Digital
    trống. Phải tự dựng profile tối thiểu từ address_map (K10)."""
    from gui.scenario_grid import ScenarioGridWindow

    win = ScenarioGridWindow(parent=None, address_map={"4231A": "GPIB0::13::INSTR"},
                             cmd_delay_s=0.3)
    try:
        monkeypatch.setattr(win, "hide", lambda: None)
        win._switch_to_digital()
        try:
            assert win._flow_win.devices, (
                "Digital không có thiết bị nào để hiện dù Classic có 1 máy (K10)")
            assert win._flow_win._connected is True
        finally:
            win._flow_win.deleteLater()
    finally:
        win.deleteLater()


def test_switch_to_digital_uses_explicit_profile_when_given(monkeypatch):
    from core.profile import ConnectionProfile, ProfileEntry
    from gui.scenario_grid import ScenarioGridWindow

    prof = ConnectionProfile(entries=[
        ProfileEntry(model_key="4231A", address="GPIB0::13::INSTR",
                     label="Máy đếm phòng A", idn="Boonton,4231A,SN1,1.0"),
    ])
    win = ScenarioGridWindow(parent=None, address_map={"4231A": "GPIB0::13::INSTR"},
                             cmd_delay_s=0.3, profile=prof)
    try:
        monkeypatch.setattr(win, "hide", lambda: None)
        win._switch_to_digital()
        try:
            names = [d["name"] for d in win._flow_win.devices]
            assert "Máy đếm phòng A" in names, (
                f"Không dùng profile đầy đủ được truyền vào (K10): {names}")
        finally:
            win._flow_win.deleteLater()
    finally:
        win.deleteLater()


def test_export_scenario_preserves_loaded_scenario_name():
    """R4-08 (test_reports/2026-10-08_round4): sau khi ghé Digital rồi xuất
    lại, tên kịch bản trong Scenario Builder đổi thành "Sơ đồ luồng" —
    export_scenario() trước đây HARDCODE tên này, đè mất tên gốc."""
    from core.scenario import Scenario, ScenarioStep

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        original = Scenario(name="51079A_via_4231A", nodes=[
            ScenarioStep(action="identify", devices=["4231A"]),
        ])
        win.load_scenario(original)
        exported = win.export_scenario()
        assert exported.name == "51079A_via_4231A", (
            f"Tên kịch bản gốc bị mất, còn lại: {exported.name!r}")
    finally:
        win.deleteLater()


def test_export_scenario_falls_back_to_default_name_in_pure_demo_mode():
    """Mở Flow Editor ĐỘC LẬP (không nạp Scenario thật nào, vd demo) ->
    chưa từng gọi load_scenario() -> vẫn cần 1 tên mặc định hợp lý,
    không crash."""
    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        exported = win.export_scenario()
        assert exported.name == "Sơ đồ luồng"
    finally:
        win.deleteLater()


# ---------------------------------------------------------------------------
# R4-07 (test_reports/2026-10-08_round4, còn mở tới vòng 5): theme Digital
# chạy xong KHÔNG có cách nào xuất số liệu đo được ra file (theme Classic
# scenario_grid.py đã có nút này từ lâu) — nút "Xuất kết quả" + _last_results
# là phần MỚI thêm để lấp khoảng trống này.
# ---------------------------------------------------------------------------

def test_on_run_result_accumulates_last_results():
    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        win._run_node_map = {}
        assert win._last_results == []
        win._on_run_result(StepResult(action="identify", node_id=999))
        assert len(win._last_results) == 1
    finally:
        win.deleteLater()


def test_export_results_button_disabled_until_run_produces_results():
    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        assert win.btn_export_results.isEnabled() is False
        win._run_node_map = {}
        win._on_run_result(StepResult(action="identify", node_id=999))
        win._on_run_finished(1, "")
        assert win.btn_export_results.isEnabled() is True
    finally:
        win.deleteLater()


def test_export_results_button_disabled_again_when_loading_new_scenario():
    from core.scenario import Scenario

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        win._run_node_map = {}
        win._on_run_result(StepResult(action="identify", node_id=999))
        win._on_run_finished(1, "")
        assert win.btn_export_results.isEnabled() is True

        win.load_scenario(Scenario(name="khac"))
        assert win.btn_export_results.isEnabled() is False
        assert win._last_results == []
    finally:
        win.deleteLater()


def test_export_run_results_calls_scenario_export_with_results(monkeypatch, tmp_path):
    from gui import flow_editor as fe_mod

    monkeypatch.setattr(fe_mod.QMessageBox, "information", lambda *a, **k: None)

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        win._run_node_map = {}
        win._on_run_result(StepResult(action="identify", node_id=999))
        win._on_run_finished(1, "")

        out_path = tmp_path / "ket_qua.xlsx"
        monkeypatch.setattr(fe_mod, "get_save_file_name",
                            lambda *a, **k: (str(out_path), ""))
        calls = {}
        def fake_export(results, path, meta=None):
            calls["results"] = results
            calls["path"] = path
            calls["meta"] = meta
            return path
        import core.scenario_export as sx
        monkeypatch.setattr(sx, "export", fake_export)

        win._export_run_results()

        assert len(calls["results"]) == 1
        assert calls["path"] == str(out_path)
    finally:
        win.deleteLater()


# ---------------------------------------------------------------------------
# K10 (test_reports/2026-10-09_khong_thiet_bi): xác nhận danh sách thiết bị
# TRỐNG (0 máy, vd máy tắt) ở Step 1 vẫn bị coi là "đã kết nối" -> Step 1
# chuyển ✓ xanh, Step 2 mở khóa dù 0 thiết bị thật nào.
# ---------------------------------------------------------------------------

def test_scan_device_with_empty_result_does_not_mark_connected():
    win = FlowEditorWindow(devices=None, parent=None, demo=False,
                           on_scan_device=lambda: {"devices": [], "address_map": {},
                                                    "cmd_delay_s": 0.1})
    try:
        win._do_scan_device()
        assert win._connected is False, (
            "Xác nhận danh sách trống vẫn coi là đã kết nối (K10)")
    finally:
        win.deleteLater()


def test_scan_device_with_real_devices_marks_connected():
    win = FlowEditorWindow(devices=None, parent=None, demo=False,
                           on_scan_device=lambda: {
                               "devices": [{"name": "4231A", "key": "4231A",
                                           "sub": "GPIB0::13::INSTR", "icon": "🔌"}],
                               "address_map": {"4231A": "GPIB0::13::INSTR"},
                               "cmd_delay_s": 0.1})
    try:
        win._do_scan_device()
        assert win._connected is True
    finally:
        win.deleteLater()


# ---------------------------------------------------------------------------
# K11 (test_reports/2026-10-09_khong_thiet_bi): sau khi đồng ý chạy mô
# phỏng, ô KẾT QUẢ hiện số liệu giả trong khung xanh như số thật, không có
# nhãn "MÔ PHỎNG" nào trên giao diện.
# ---------------------------------------------------------------------------

def test_result_label_shows_mo_phong_prefix_when_last_run_was_mock():
    from types import SimpleNamespace

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        win._last_run_mock = True
        fake_node = SimpleNamespace(_last_result_ok=True,
                                    _last_result_text="BOONTON,4231A,00000001,REV1.0")
        win._update_result_display(fake_node)
        assert win.lbl_result.text().startswith("🧪 MÔ PHỎNG"), (
            f"Kết quả mô phỏng không có nhãn cảnh báo (K11): {win.lbl_result.text()!r}")
    finally:
        win.deleteLater()


def test_result_label_has_no_mo_phong_prefix_for_real_run():
    from types import SimpleNamespace

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        win._last_run_mock = False
        fake_node = SimpleNamespace(_last_result_ok=True, _last_result_text="1.000000 GHz")
        win._update_result_display(fake_node)
        assert win.lbl_result.text() == "1.000000 GHz"
    finally:
        win.deleteLater()


def test_do_run_sets_last_run_mock_based_on_address_map(monkeypatch):
    from gui import flow_editor as fe_mod

    win = FlowEditorWindow(devices=_DEVICES, parent=None, demo=False)
    try:
        monkeypatch.setattr(fe_mod, "confirm_yes_no", lambda *a, **k: True)
        monkeypatch.setattr(fe_mod.QMessageBox, "warning", lambda *a, **k: None)
        win._do_run()   # kịch bản trống (demo=False, chưa load node) -> dừng sớm sau khi gán cờ
        assert win._last_run_mock is True, (
            "Không đánh dấu lần chạy là mô phỏng dù address_map rỗng (K11)")
    finally:
        if win.worker:
            win.worker.wait(2000)
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
