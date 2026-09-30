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

from gui.scenario_grid import StepEditorDialog

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
