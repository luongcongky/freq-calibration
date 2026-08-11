"""
take_screenshots.py
===================
Script tự động chụp ảnh tất cả màn hình / popup của freq_calibration.
Chạy từ thư mục gốc dự án:
    python take_screenshots.py

Ảnh được lưu vào thư mục ./screenshots/
"""

import sys
import os
import time

# Phải chạy từ thư mục gốc dự án
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon

app = QApplication(sys.argv)

# Load theme
from gui.theme import build_global_qss, Colors
app.setStyleSheet(build_global_qss())
try:
    app.setWindowIcon(QIcon("gui/logo.ico"))
except Exception:
    pass

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(OUT_DIR, exist_ok=True)

def save_shot(widget, name):
    """Chụp và lưu ảnh widget."""
    widget.show()
    widget.raise_()
    widget.activateWindow()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    screen = app.primaryScreen()
    pixmap = screen.grabWindow(int(widget.winId()))
    path = os.path.join(OUT_DIR, f"{name}.png")
    pixmap.save(path, "PNG")
    print(f"  OK  {path}")
    return path

# ── 1. SESSION MANAGER (cửa sổ khởi động) ───────────────────────────────────
print("\n[1] Session Manager Window...")
from gui.session_manager import SessionManagerWindow
win_session = SessionManagerWindow()
win_session.setWindowTitle("Phiên Kiểm Định — FREQ-CAL PRO")
save_shot(win_session, "01_session_manager")
win_session.hide()

# ── 2. SCENARIO BUILDER (cửa sổ chính) ──────────────────────────────────────
print("\n[2] Scenario Builder (Scenario Grid Window)...")
from gui.scenario_grid import ScenarioGridWindow
win_scenario = ScenarioGridWindow()
win_scenario.resize(1280, 780)
save_shot(win_scenario, "02_scenario_builder")

# ── 3. STEP EDITOR DIALOG (popup Bước đơn) ───────────────────────────────────
print("\n[3] Step Editor Dialog...")
from gui.scenario_grid import StepEditorDialog
from core.scenario import ScenarioStep
from drivers import DEVICE_REGISTRY
dev_keys = list(DEVICE_REGISTRY.keys())
step = ScenarioStep(
    action="raw_scpi",
    devices=[dev_keys[0]] if dev_keys else [],
    params={"__template__": ":FREQ {freq}", "freq": "1E9"},
    note="Dat tan so 1 GHz",
)
dlg_step = StepEditorDialog(parent=None, step=step, connected_keys=set(dev_keys))
dlg_step.setWindowTitle("Chinh sua Buoc - FREQ-CAL PRO")
dlg_step.resize(700, 500)
save_shot(dlg_step, "03_step_editor")
dlg_step.hide()

# ── 4. LOOP EDITOR DIALOG ─────────────────────────────────────────────────────
print("\n[4] Loop Editor Dialog...")
from gui.scenario_grid import LoopEditorDialog
from core.scenario import LoopBlock
loop = LoopBlock(count=5, body=[])
dlg_loop = LoopEditorDialog(parent=None, loop=loop, device_choices=dev_keys)
dlg_loop.setWindowTitle("Chinh sua Loop - FREQ-CAL PRO")
save_shot(dlg_loop, "04_loop_editor")
dlg_loop.hide()

# ── 5. IF EDITOR DIALOG ───────────────────────────────────────────────────────
print("\n[5] If Editor Dialog...")
from gui.scenario_grid import IfEditorDialog
from core.scenario import IfBlock, Branch, Condition
branch_true = Branch(condition=Condition(op=">", value=0.0), body=[])
branch_else = Branch(condition=None, body=[])
ib = IfBlock(branches=[branch_true, branch_else])
dlg_if = IfEditorDialog(parent=None, ib=ib, device_choices=dev_keys)
dlg_if.setWindowTitle("Chinh sua If - FREQ-CAL PRO")
save_shot(dlg_if, "05_if_editor")
dlg_if.hide()

# ── 6. CONDITION DIALOG ───────────────────────────────────────────────────────
print("\n[6] Condition Dialog...")
from gui.scenario_grid import ConditionDialog
from core.scenario import Condition
cond = Condition(op=">", value=0.5)
dlg_cond = ConditionDialog(parent=None, condition=cond, device_choices=dev_keys)
dlg_cond.setWindowTitle("Dieu kien - FREQ-CAL PRO")
save_shot(dlg_cond, "06_condition_dialog")
dlg_cond.hide()

# ── 7. DEVICE MANAGER DIALOG ─────────────────────────────────────────────────
print("\n[7] Device Manager Dialog...")
from gui.device_manager import DeviceManagerDialog
dlg_dev = DeviceManagerDialog(parent=None, mock=True)
dlg_dev.setWindowTitle("Quản lý thiết bị — FREQ-CAL PRO")
save_shot(dlg_dev, "07_device_manager")
dlg_dev.hide()

# ── 8. COMMAND REFERENCE DIALOG ──────────────────────────────────────────────
print("\n[8] Command Reference Dialog...")
from gui.command_reference import CommandReferenceDialog
dlg_cmd = CommandReferenceDialog(parent=None)
dlg_cmd.setWindowTitle("Tập lệnh SCPI — FREQ-CAL PRO")
save_shot(dlg_cmd, "08_command_reference")
dlg_cmd.hide()

# ── 9. FLOW EDITOR WINDOW ─────────────────────────────────────────────────────
print("\n[9] Flow Editor Window...")
try:
    from gui.flow_editor import FlowEditorWindow
    win_flow = FlowEditorWindow(demo=True)
    win_flow.resize(1100, 700)
    save_shot(win_flow, "09_flow_editor")
    win_flow.hide()
except Exception as e:
    print(f"  ! Khong the chup Flow Editor: {e}")

print(f"\nXONG! Anh luu tai: {OUT_DIR}")
sys.exit(0)
