"""
unit_test/test_scenario_grid.py
=================================
Test các sửa lỗi GUI trong gui/scenario_grid.py phát hiện ở vòng test
2026-09-30/10-01 (test_reports/2026-09-30_full_gui/BAO_CAO_TEST.md):

  BUG-13: chọn 1 lệnh (vd "*IDN?") trong StepEditorDialog TRƯỚC khi tick
          thiết bị -> tick thiết bị rebuild lại cmd_list -> mất lựa chọn.
  BUG-14: "+ Bước"/"+ Loop"/"+ If" tạo node mới luôn bị ép enabled=False.

Không gọi dlg.exec_() (modal, treo test) — chỉ dựng dialog rồi thao tác
trực tiếp lên widget, giống cách unit_test/test_report_preview.py test
các dialog/widget Qt khác trong repo.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from core.scenario import ScenarioStep
from core.scenario_runner import StepResult
from gui.scenario_grid import ScenarioGridWindow, StepEditorDialog

_app = QApplication.instance() or QApplication([])


def _check_first_device(dlg: StepEditorDialog):
    item = dlg.dev_list.item(0)
    item.setCheckState(Qt.Checked)


def test_selecting_command_before_ticking_device_keeps_selection():
    dlg = StepEditorDialog(parent=None, connected_keys=set())
    try:
        dlg._select_cmd_by_original("*IDN?")
        assert dlg.cmd_list.currentItem() is not None
        assert dlg.cmd_list.currentItem().data(Qt.UserRole).cmd == "*IDN?"

        _check_first_device(dlg)  # itemChanged -> _refresh_commands() (clear + rebuild)

        current = dlg.cmd_list.currentItem()
        assert current is not None, "Mất lựa chọn lệnh sau khi tick thiết bị (BUG-13)"
        assert current.data(Qt.UserRole).cmd == "*IDN?"
    finally:
        dlg.deleteLater()


def test_unselected_device_specific_command_not_restored_after_untick():
    """Lệnh RIÊNG của 1 thiết bị (không phải lệnh chung) thì khi bỏ tick
    thiết bị đó, lệnh không còn trong danh sách -> không có gì để chọn lại
    (khác với lệnh chung luôn còn, như test ở trên)."""
    dlg = StepEditorDialog(parent=None, connected_keys=set())
    try:
        _check_first_device(dlg)
        device_cmds = [dlg.cmd_list.item(i) for i in range(dlg.cmd_list.count())
                       if dlg.cmd_list.item(i).data(Qt.UserRole + 1) not in
                       ("__wait__", "__break__", "__common__", None)]
        assert device_cmds, "Thiết bị đầu tiên trong registry không có lệnh riêng nào để test"
        dlg.cmd_list.setCurrentItem(device_cmds[0])
        selected_cmd = device_cmds[0].data(Qt.UserRole).cmd

        dlg.dev_list.item(0).setCheckState(Qt.Unchecked)

        remaining = [dlg.cmd_list.item(i).data(Qt.UserRole).cmd
                     for i in range(dlg.cmd_list.count())
                     if dlg.cmd_list.item(i).data(Qt.UserRole) is not None]
        assert selected_cmd not in remaining or dlg.cmd_list.currentItem() is None
    finally:
        dlg.deleteLater()


def test_add_step_dialog_does_not_force_disabled():
    """ScenarioStep.enabled mặc định True (core/scenario.py) — get_step() của
    dialog không tự ép False; việc KHÔNG ép False nữa ở
    ScenarioGridWindow._add_step/_add_block (BUG-14) được xác nhận gián
    tiếp qua test này: dialog trả về step với enabled mặc định dataclass."""
    from core.scenario import ScenarioStep
    dlg = StepEditorDialog(parent=None, connected_keys=set())
    try:
        _check_first_device(dlg)
        dlg._select_cmd_by_original("*IDN?")
        dlg._on_accept()
        step = dlg.get_step()
        assert isinstance(step, ScenarioStep)
        assert step.enabled is True
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# REG-RAM-01: mở/đóng Scenario Builder không trả lại RAM (+30 MB/lần, chỉ
# được GC vòng lặp dọn bất chợt) — cửa sổ top-level (parent=None) không có
# WA_DeleteOnClose nên close() chỉ ẨN, không giải phóng cây widget C++, và
# session_manager giữ nguyên tham chiếu Python tới cửa sổ đã đóng cho tới
# lần mở kế tiếp.
# ---------------------------------------------------------------------------

def test_scenario_grid_window_has_delete_on_close_attribute():
    win = ScenarioGridWindow(parent=None)
    try:
        assert win.testAttribute(Qt.WA_DeleteOnClose) is True
    finally:
        win.setAttribute(Qt.WA_DeleteOnClose, False)  # tránh double-free khi deleteLater() ở finally
        win.deleteLater()


def test_scenario_grid_window_on_closed_callback_fires_on_close():
    calls = []
    win = ScenarioGridWindow(parent=None, on_closed=lambda: calls.append(1))
    win.setAttribute(Qt.WA_DeleteOnClose, False)  # tránh double-free trong test (không có event loop chạy deleteLater)
    win.close()
    assert calls == [1]


def test_scenario_grid_window_closed_callback_not_called_when_cancelled(monkeypatch):
    """Đang chạy dở (worker) -> closeEvent ignore, KHÔNG gọi on_closed. Chặn
    QMessageBox.warning (modal, sẽ treo test chờ click) bằng monkeypatch."""
    from gui import scenario_grid

    class _FakeWorker:
        def isRunning(self):
            return True

    monkeypatch.setattr(scenario_grid.QMessageBox, "warning", lambda *a, **k: None)
    calls = []
    win = ScenarioGridWindow(parent=None, on_closed=lambda: calls.append(1))
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win.worker = _FakeWorker()
        win.close()
        assert calls == []
    finally:
        win.worker = None
        win.deleteLater()


# ---------------------------------------------------------------------------
# BUG-20: 1 bước chạy trên NHIỀU thiết bị (vd 4231A + NRVD) — ô "Kết quả"
# chỉ hiện kết quả của 1 máy, kết quả máy còn lại chỉ thấy trong log.
# ---------------------------------------------------------------------------

def test_multi_device_step_result_shows_both_devices_tagged():
    step = ScenarioStep(action="raw_scpi", devices=["4231A", "NRVD"],
                        params={"__template__": "MEAS?", "__is_query__": True})
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win.scenario.nodes = [step]
        win._refresh_tree()
        node_id = id(step)

        res1 = StepResult(action="raw_scpi", device_key="4231A", node_id=node_id,
                          is_query=True, text="OK", value=None)
        res2 = StepResult(action="raw_scpi", device_key="NRVD", node_id=node_id,
                          is_query=True, text="OK", value=None)
        win._on_result(res1)
        win._on_result(res2)

        item = win._id_to_item.get(node_id)
        assert item is not None
        text = item.text(4)
        assert "[4231A]" in text and "[NRVD]" in text, (
            f"Kết quả thiếu 1 trong 2 máy (BUG-20): {text!r}")
    finally:
        win.deleteLater()


def test_multi_device_write_command_shows_placeholder_for_each_device():
    """Lệnh GHI (result_cell() rỗng) trên NHIỀU thiết bị — trước đây cả 2
    kết quả rỗng bị bộ lọc "bỏ ô trống" nuốt mất hoàn toàn, không còn gì
    hiện trên lưới (chỉ thấy trong log) dù cả 2 máy đều đã chạy xong."""
    step = ScenarioStep(action="raw_scpi", devices=["4231A", "NRVD"],
                        params={"__template__": "SENS:FREQ 1E9", "__is_query__": False})
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win.scenario.nodes = [step]
        win._refresh_tree()
        node_id = id(step)

        res1 = StepResult(action="raw_scpi", device_key="4231A", node_id=node_id, ok=True)
        res2 = StepResult(action="raw_scpi", device_key="NRVD", node_id=node_id, ok=True)
        win._on_result(res1)
        win._on_result(res2)

        item = win._id_to_item.get(node_id)
        text = item.text(4)
        assert "[4231A]" in text and "[NRVD]" in text, (
            f"Kết quả lệnh ghi của 1 trong 2 máy biến mất khỏi lưới (BUG-20): {text!r}")
        assert item.toolTip(4) == text
    finally:
        win.deleteLater()


def test_single_device_step_result_not_tagged():
    """Bước chỉ 1 thiết bị — KHÔNG gắn thêm [tên máy] vào cột Kết quả như
    trước đây (chỉ bước nhiều máy mới cần phân biệt)."""
    step = ScenarioStep(action="raw_scpi", devices=["4231A"],
                        params={"__template__": "MEAS?", "__is_query__": True})
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win.scenario.nodes = [step]
        win._refresh_tree()
        node_id = id(step)

        res = StepResult(action="raw_scpi", device_key="4231A", node_id=node_id,
                         is_query=True, text="OK", value=None)
        win._on_result(res)

        item = win._id_to_item.get(node_id)
        assert item.text(4) == "OK"
    finally:
        win.deleteLater()


# ---------------------------------------------------------------------------
# BUG-23: kịch bản dài chỉ có log cuộn "B123 ..." mỗi bước, không biết tổng
# số bước/% tiến trình.
# ---------------------------------------------------------------------------

def test_update_run_progress_status_shows_percent_without_loop():
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win._run_total_steps = 4
        win._run_done_steps = 1
        win._update_run_progress_status()
        assert win.statusBar().currentMessage() == "Đã chạy: 1/4 bước (25%)"
    finally:
        win.deleteLater()


def test_update_run_progress_status_shows_counter_only_with_loop():
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win._run_total_steps = None   # có vòng lặp -> không biết trước tổng
        win._run_done_steps = 137
        win._update_run_progress_status()
        assert win.statusBar().currentMessage() == "Đã chạy: 137 bước"
        assert "%" not in win.statusBar().currentMessage()
    finally:
        win.deleteLater()


def test_run_detects_loop_and_leaves_total_steps_unknown(monkeypatch):
    """_run() phải tự nhận ra kịch bản có LoopBlock (ở bất kỳ độ sâu nào,
    kể cả trong nhánh If) để không hiện % tiến trình SAI cho tổng không cố
    định — chỉ kiểm tra việc tính total_steps, không chạy worker thật."""
    from core.scenario import ScenarioStep, LoopBlock

    step = ScenarioStep(action="wait", devices=[], params={"seconds": 0})
    loop = LoopBlock(body=[step])
    win = ScenarioGridWindow(parent=None)
    win.setAttribute(Qt.WA_DeleteOnClose, False)
    try:
        win.scenario.nodes = [step, loop]
        monkeypatch.setattr(win, "worker", None)
        # Né đoạn thật gửi lệnh (validate_scenario/ScenarioWorker) — chỉ
        # cần test tới chỗ _run_total_steps được tính xong.
        monkeypatch.setattr("gui.scenario_grid.validate_scenario", lambda scn: [])
        monkeypatch.setattr(win, "address_map", {})
        monkeypatch.setattr(ScenarioGridWindow, "all_device_keys", lambda self: [], raising=False)
        win.scenario.all_device_keys = lambda: []

        class _FakeWorker:
            def __init__(self, *a, **k):
                pass
            def start(self):
                pass
            result_ready = type("Sig", (), {"connect": lambda self, f: None})()
            finished_all = type("Sig", (), {"connect": lambda self, f: None})()
            failed = type("Sig", (), {"connect": lambda self, f: None})()

        monkeypatch.setattr("gui.scenario_grid.ScenarioWorker", _FakeWorker)
        win._run()
        assert win._run_total_steps is None, "Có LoopBlock nhưng vẫn coi tổng bước là cố định"
    finally:
        win.deleteLater()
