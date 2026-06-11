"""
gui/scenario_grid.py
====================
Màn hình chính: "Scenario Builder" dạng CÂY (tree) có luồng điều khiển.

Một kịch bản gồm các node cấp ngoài: Bước đơn, 🔁 Loop (lặp N lần), ❓ If (rẽ
nhiều nhánh). Loop/If chứa các bước con (1 cấp, không lồng khối trong khối).

Khởi chạy: `python main.py` hoặc `python -m gui.scenario_grid`.
Logic chạy ở core/scenario_runner.py (không phụ thuộc Qt) — đã test bằng pytest.
"""

from __future__ import annotations

import sys
import logging
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QDialog,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit, QFormLayout,
    QDialogButtonBox, QHeaderView, QFileDialog, QMessageBox,
    QAbstractItemView, QTextEdit, QStyle, QStyleOptionButton, QSpinBox,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect
from PyQt5.QtGui import QColor, QFont

from drivers import DEVICE_REGISTRY
from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    ACTION_SPECS, OPERATORS, OP_LABELS,
    actions_for_devices, validate_scenario, node_kind, node_from_dict,
)
from core.scenario_runner import ScenarioRunner, StepResult
from core.commands import (
    parse_cmd, get_commands_for, get_common_commands, load_custom, WAIT_CMD,
)

logger = logging.getLogger(__name__)

from gui.theme import Colors, build_global_qss

COLS = ["Bật / Nội dung", "Mô tả lệnh", "Thiết bị", "Tham số / Điều kiện", "Kết quả", "Trạng thái"]

# Lưu metadata vào item qua các role riêng. KHÔNG lưu list/dict (PyQt sao chép
# list/dict -> mất tham chiếu tới scenario thật); chỉ lưu object/str (giữ ref).
ROLE_OBJ = Qt.UserRole          # node/step/branch object
ROLE_KIND = Qt.UserRole + 1     # "step" | "loop" | "if" | "branch"
ROLE_PARENT = Qt.UserRole + 2   # object cha (None nếu node cấp ngoài)


# ===========================================================================
# Header có checkbox "chọn/bỏ tất cả" ở cột 0
# ===========================================================================

class CheckBoxHeader(QHeaderView):
    toggled_all = pyqtSignal(bool)

    def __init__(self, parent=None, label="Bật"):
        super().__init__(Qt.Horizontal, parent)
        self._checked = False
        self._label = label
        self.setSectionsClickable(True)

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.updateSection(0)

    def paintSection(self, painter, rect, logicalIndex):
        # Cột 1+ do QSS vẽ (đã có border-bottom + border-right). Chỉ cột 0 vẽ tay
        # để chèn ô tick — nên tự vẽ luôn đường ngang dưới + dọc phải cho đồng bộ.
        if logicalIndex != 0:
            super().paintSection(painter, rect, logicalIndex)
            return
        painter.save()
        painter.fillRect(rect, QColor(Colors.BG_CARD))
        painter.setPen(QColor(Colors.BORDER))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())   # ngang dưới
        painter.drawLine(rect.topRight(), rect.bottomRight())     # dọc phải (ngăn cách cột)
        sz = 15
        cb = QRect(rect.x() + 6, rect.y() + (rect.height() - sz) // 2, sz, sz)
        opt = QStyleOptionButton()
        opt.rect = cb
        opt.state = QStyle.State_Enabled | (QStyle.State_On if self._checked else QStyle.State_Off)
        self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, painter)
        painter.setPen(QColor(Colors.TEXT_DIM))
        text_rect = QRect(cb.right() + 6, rect.y(),
                          rect.width() - (cb.right() + 6 - rect.x()), rect.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._label)
        painter.restore()

    def _checkbox_rect(self) -> QRect:
        """Vùng hình ô tick ở cột 0 (toạ độ viewport của header)."""
        sz = 15
        x0 = self.sectionViewportPosition(0)
        return QRect(x0 + 6, (self.height() - sz) // 2, sz, sz)

    def mousePressEvent(self, event):
        # Chỉ bật/tắt "chọn tất cả" khi bấm ĐÚNG vào ô tick. Mọi chỗ khác — kể cả
        # mép giữa các cột để KÉO RỘNG/HẸP — đều để QHeaderView xử lý như thường.
        if self._checkbox_rect().contains(event.pos()):
            self.setChecked(not self._checked)
            self.toggled_all.emit(self._checked)
            return
        super().mousePressEvent(event)


# ===========================================================================
# Dialog: soạn bước đơn
# ===========================================================================

class StepEditorDialog(QDialog):
    def __init__(self, parent=None, step: ScenarioStep | None = None,
                 connected_keys: set | None = None):
        super().__init__(parent)
        self._connected = connected_keys or set()
        self.setWindowTitle("Soạn bước")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self._param_widgets: dict[str, object] = {}
        self._parsed_params: list = []
        self._current_template: str = ""
        self._current_is_query: bool = False
        self._result: ScenarioStep | None = None

        root = QVBoxLayout(self)
        root.setSpacing(6)

        root.addWidget(QLabel("Thiết bị (chọn 1 hoặc nhiều — chạy cùng bước):"))
        root.addWidget(QLabel("🟢 = đang kết nối   ·   ○ = chưa thấy"))
        self.dev_list = QListWidget()
        self.dev_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.dev_list.setMaximumHeight(150)
        ordered = sorted(DEVICE_REGISTRY.items(),
                         key=lambda kv: (kv[0] not in self._connected, kv[0]))
        for key, entry in ordered:
            is_conn = key in self._connected
            dot = "🟢" if is_conn else "○"
            suffix = "   ✓ đang kết nối" if is_conn else ""
            it = QListWidgetItem(f"{dot}  {key}  —  {entry['vendor']} ({entry['category']}){suffix}")
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setForeground(QColor(Colors.ACCENT_GREEN) if is_conn else QColor(Colors.TEXT_DIM))
            self.dev_list.addItem(it)
        self.dev_list.itemChanged.connect(lambda *_: self._refresh_commands())
        root.addWidget(self.dev_list)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Lệnh:"))
        self.cmd_search = QLineEdit()
        self.cmd_search.setPlaceholderText("Tìm lệnh…")
        self.cmd_search.textChanged.connect(self._filter_commands)
        search_row.addWidget(self.cmd_search)
        root.addLayout(search_row)

        self.cmd_list = QListWidget()
        self.cmd_list.setMinimumHeight(160)
        # Giữ NGUYÊN màu nền dòng đang chọn kể cả khi list mất focus (vd khi
        # bấm sang ô Ghi chú) — tránh cảm giác lệnh bị bỏ chọn.
        self.cmd_list.setStyleSheet(
            f"QListWidget::item:selected {{ background:{Colors.ACCENT_CYAN};"
            f" color:{Colors.BG_WINDOW}; }}"
        )
        self.cmd_list.currentItemChanged.connect(self._on_cmd_selected)
        root.addWidget(self.cmd_list)

        self.cmd_info = QLabel("")
        self.cmd_info.setWordWrap(True)
        self.cmd_info.setStyleSheet("color: #a0a5ad; font-size: 11px;")
        root.addWidget(self.cmd_info)

        self.param_form = QFormLayout()
        root.addLayout(self.param_form)

        note_form = QFormLayout()
        self.note_edit = QLineEdit()
        note_form.addRow("Ghi chú:", self.note_edit)
        root.addLayout(note_form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._refresh_commands()
        if step is not None:
            self._load_step(step)

    # ── helpers ────────────────────────────────────────────────────────────

    def _selected_devices(self):
        return [self.dev_list.item(i).data(Qt.UserRole)
                for i in range(self.dev_list.count())
                if self.dev_list.item(i).checkState() == Qt.Checked]

    def _add_header_item(self, text: str):
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        f = item.font(); f.setBold(True); item.setFont(f)
        item.setForeground(QColor(Colors.TEXT_DIM))
        item.setData(Qt.UserRole, None)
        self.cmd_list.addItem(item)

    def _add_cmd_item(self, cmd, model_key: str):
        item = QListWidgetItem(f"  {cmd.cmd}")
        item.setFont(QFont("Consolas", 9))
        item.setData(Qt.UserRole, cmd)
        item.setData(Qt.UserRole + 1, model_key)
        item.setToolTip(cmd.desc + ("\n" + cmd.note if cmd.note else ""))
        self.cmd_list.addItem(item)

    # ── command list ────────────────────────────────────────────────────────

    def _refresh_commands(self):
        devices = self._selected_devices()
        self.cmd_list.clear()
        custom = load_custom()

        self._add_header_item("── Điều khiển kịch bản ──")
        self._add_cmd_item(WAIT_CMD, "__wait__")

        self._add_header_item("── Lệnh chung (IEEE 488.2) ──")
        for cmd in get_common_commands(custom):
            self._add_cmd_item(cmd, "__common__")

        for dk in devices:
            cmds = get_commands_for(dk, custom)
            if not cmds:
                continue
            cls = DEVICE_REGISTRY.get(dk, {}).get("cls")
            model_name = getattr(cls, "MODEL_NAME", dk) if cls else dk
            self._add_header_item(f"── {model_name} ({dk}) ──")
            for cmd in cmds:
                self._add_cmd_item(cmd, dk)

        self._filter_commands(self.cmd_search.text())

    def _filter_commands(self, text: str):
        text = text.strip().lower()
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            if item.data(Qt.UserRole) is None:
                continue
            cmd = item.data(Qt.UserRole)
            match = not text or text in cmd.cmd.lower() or text in cmd.desc.lower()
            item.setHidden(not match)

        # Hide headers whose entire section is hidden
        i = 0
        while i < self.cmd_list.count():
            item = self.cmd_list.item(i)
            if item.data(Qt.UserRole) is None:
                j = i + 1
                has_visible = False
                while j < self.cmd_list.count() and self.cmd_list.item(j).data(Qt.UserRole) is not None:
                    if not self.cmd_list.item(j).isHidden():
                        has_visible = True
                        break
                    j += 1
                item.setHidden(not has_visible)
            i += 1

    def _on_cmd_selected(self, current, _prev):
        if current is None or current.data(Qt.UserRole) is None:
            return
        cmd = current.data(Qt.UserRole)
        template, params, is_query = parse_cmd(cmd)
        self._current_template = template
        self._current_is_query = is_query
        self._parsed_params = params

        parts = [cmd.desc]
        if cmd.note:
            parts.append(f"({cmd.note})")
        if is_query:
            parts.append("→ trả kết quả")
        self.cmd_info.setText("  ".join(parts))

        self._rebuild_param_form(params)

    def _rebuild_param_form(self, params):
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self._param_widgets.clear()
        for p in params:
            if p.ptype == "enum":
                w = QComboBox()
                for c in p.choices:
                    w.addItem(c, c)
            else:
                w = QLineEdit(str(p.default))
            label = p.label + (f" ({p.unit})" if p.unit else "") + ":"
            self.param_form.addRow(label, w)
            self._param_widgets[p.name] = w

    # ── load existing step ──────────────────────────────────────────────────

    def _load_step(self, step: ScenarioStep):
        for i in range(self.dev_list.count()):
            it = self.dev_list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in step.devices else Qt.Unchecked)
        self._refresh_commands()

        if step.action == "wait":
            self._select_by_model_key("__wait__")
            w = self._param_widgets.get("seconds")
            if isinstance(w, QLineEdit):
                w.setText(str(step.params.get("seconds", 0.5)))
        elif step.action == "raw_scpi":
            self._select_cmd_by_original(step.params.get("__cmd_original__", ""))
            for name, w in self._param_widgets.items():
                if name in step.params:
                    val = step.params[name]
                    if isinstance(w, QComboBox):
                        idx = w.findData(str(val))
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                    elif isinstance(w, QLineEdit):
                        w.setText(str(val))
        self.note_edit.setText(step.note)

    def _select_by_model_key(self, model_key: str):
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            if item.data(Qt.UserRole + 1) == model_key:
                self.cmd_list.setCurrentItem(item)
                return

    def _select_cmd_by_original(self, original: str):
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            cmd = item.data(Qt.UserRole)
            if cmd is not None and cmd.cmd == original:
                self.cmd_list.setCurrentItem(item)
                return

    # ── accept ──────────────────────────────────────────────────────────────

    def _on_accept(self):
        item = self.cmd_list.currentItem()
        if item is None or item.data(Qt.UserRole) is None:
            QMessageBox.warning(self, "Thiếu", "Chưa chọn lệnh."); return

        model_key = item.data(Qt.UserRole + 1)
        cmd = item.data(Qt.UserRole)
        note = self.note_edit.text().strip()

        if model_key == "__wait__":
            w = self._param_widgets.get("seconds")
            try:
                s_val = float(w.text().strip()) if isinstance(w, QLineEdit) else 0.5
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "Sai tham số", "Thời gian chờ phải là số."); return
            self._result = ScenarioStep(action="wait", devices=[], params={"seconds": s_val}, note=note)
            self.accept()
            return

        devices = self._selected_devices()
        if not devices:
            QMessageBox.warning(self, "Thiếu thiết bị", "Chọn ít nhất 1 thiết bị cho lệnh này."); return

        params = {
            "__template__":     self._current_template,
            "__is_query__":     self._current_is_query,
            "__cmd_original__": cmd.cmd,
            "__cmd_desc__":     cmd.desc,
        }

        for p in self._parsed_params:
            w = self._param_widgets.get(p.name)
            if w is None:
                continue
            if isinstance(w, QComboBox):
                params[p.name] = w.currentData()
            else:
                raw = w.text().strip()
                if p.ptype == "int":
                    try:
                        params[p.name] = int(float(raw))
                    except ValueError:
                        QMessageBox.warning(self, "Sai tham số",
                                            f"'{p.label}' phải là số nguyên."); return
                else:
                    try:
                        params[p.name] = float(raw)
                    except ValueError:
                        QMessageBox.warning(self, "Sai tham số",
                                            f"'{p.label}' phải là số."); return

        self._result = ScenarioStep(action="raw_scpi", devices=devices, params=params, note=note)
        self.accept()

    def get_step(self) -> ScenarioStep:
        return self._result


# ===========================================================================
# Dialog: soạn Loop
# ===========================================================================

class LoopEditorDialog(QDialog):
    def __init__(self, parent=None, loop: LoopBlock | None = None):
        super().__init__(parent)
        self.setWindowTitle("Soạn vòng lặp (Loop)")
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.spin = QSpinBox(); self.spin.setRange(1, 100000); self.spin.setValue(2)
        self.note = QLineEdit()
        form.addRow("Số lần lặp:", self.spin)
        form.addRow("Ghi chú:", self.note)
        root.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)
        if loop is not None:
            self.spin.setValue(loop.count); self.note.setText(loop.note)

    def get_values(self):
        return self.spin.value(), self.note.text().strip()


# ===========================================================================
# Dialog: soạn điều kiện
# ===========================================================================

class ConditionDialog(QDialog):
    def __init__(self, parent=None, condition: Condition | None = None,
                 device_choices: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Điều kiện rẽ nhánh")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("So sánh giá trị đo gần nhất", "measure")
        self.kind.addItem("Theo trạng thái bước trước (OK/Lỗi)", "status")
        self.kind.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Loại điều kiện:", self.kind)

        self.device = QComboBox()
        self.device.addItem("(đo gần nhất — bất kỳ)", "")
        for k in (device_choices or list(DEVICE_REGISTRY.keys())):
            self.device.addItem(k, k)
        form.addRow("Thiết bị nguồn:", self.device)

        self.op = QComboBox()
        for o in OPERATORS:
            self.op.addItem(f"{o}  ({OP_LABELS[o]})", o)
        self.op.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Toán tử:", self.op)

        self.val = QLineEdit("0")
        form.addRow("Ngưỡng:", self.val)
        self.val2 = QLineEdit("0")
        form.addRow("Ngưỡng 2 (khoảng):", self.val2)

        self.status = QComboBox()
        self.status.addItem("OK", "ok"); self.status.addItem("LỖI", "error")
        form.addRow("Trạng thái:", self.status)
        root.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        if condition is not None:
            self._load(condition)
        self._update_visibility()

    def _load(self, c: Condition):
        self.kind.setCurrentIndex(self.kind.findData(c.kind))
        self.device.setCurrentIndex(max(0, self.device.findData(c.device)))
        self.op.setCurrentIndex(max(0, self.op.findData(c.op)))
        self.val.setText(str(c.value)); self.val2.setText(str(c.value2))
        self.status.setCurrentIndex(self.status.findData(c.status))

    def _update_visibility(self):
        is_measure = self.kind.currentData() == "measure"
        for w in (self.device, self.op, self.val):
            w.setEnabled(is_measure)
        self.val2.setEnabled(is_measure and self.op.currentData() in ("between", "outside"))
        self.status.setEnabled(not is_measure)

    def _on_accept(self):
        kind = self.kind.currentData()
        if kind == "measure":
            try:
                v = float(self.val.text().strip()); v2 = float(self.val2.text().strip() or 0)
            except ValueError:
                QMessageBox.warning(self, "Sai", "Ngưỡng phải là số."); return
            self._result = Condition(kind="measure", device=self.device.currentData(),
                                     op=self.op.currentData(), value=v, value2=v2)
        else:
            self._result = Condition(kind="status", status=self.status.currentData())
        self.accept()

    def get_condition(self) -> Condition:
        return self._result


# ===========================================================================
# Dialog: quản lý nhánh của If
# ===========================================================================

class IfEditorDialog(QDialog):
    def __init__(self, parent=None, ib: IfBlock | None = None,
                 device_choices: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Soạn rẽ nhánh (If / Ngược lại nếu / Ngược lại)")
        self.setMinimumWidth(520)
        self._devices = device_choices or list(DEVICE_REGISTRY.keys())
        # làm việc trên bản sao branch (giữ body nếu sửa).
        self.branches: list[Branch] = []
        if ib is not None:
            self.branches = [Branch.from_dict(b.to_dict()) for b in ib.branches]
            self.note = ib.note
        else:
            self.branches = [Branch(condition=Condition()), Branch(condition=None)]
            self.note = ""

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Các nhánh (xét lần lượt từ trên xuống, chạy nhánh đúng đầu tiên):"))
        self.lst = QListWidget()
        root.addWidget(self.lst)

        bar = QHBoxLayout()
        for text, slot in [("➕ Nhánh điều kiện", self._add_cond),
                           ("➕ Ngược lại (ELSE)", self._add_else),
                           ("✏ Sửa điều kiện", self._edit_cond),
                           ("🗑 Xóa nhánh", self._del),
                           ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1))]:
            b = QPushButton(text); b.clicked.connect(slot); bar.addWidget(b)
        root.addLayout(bar)

        nform = QFormLayout()
        self.note_edit = QLineEdit(self.note)
        nform.addRow("Ghi chú:", self.note_edit)
        root.addLayout(nform)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._refresh()

    def _refresh(self):
        self.lst.clear()
        for i, b in enumerate(self.branches):
            if b.condition is None:
                label = "Ngược lại (ELSE)"
            elif i == 0:
                label = f"Nếu  {b.condition.describe()}"
            else:
                label = f"Ngược lại nếu  {b.condition.describe()}"
            n = len(b.body)
            self.lst.addItem(f"{label}    [{n} bước con]")

    def _add_cond(self):
        dlg = ConditionDialog(self, device_choices=self._devices)
        if dlg.exec_() == QDialog.Accepted:
            # chèn trước nhánh ELSE nếu có.
            insert_at = len(self.branches)
            for i, b in enumerate(self.branches):
                if b.condition is None:
                    insert_at = i; break
            self.branches.insert(insert_at, Branch(condition=dlg.get_condition()))
            self._refresh()

    def _add_else(self):
        if any(b.condition is None for b in self.branches):
            QMessageBox.information(self, "Đã có", "Chỉ được 1 nhánh 'Ngược lại'."); return
        self.branches.append(Branch(condition=None))
        self._refresh()

    def _edit_cond(self):
        r = self.lst.currentRow()
        if r < 0:
            return
        b = self.branches[r]
        if b.condition is None:
            QMessageBox.information(self, "ELSE", "Nhánh 'Ngược lại' không có điều kiện."); return
        dlg = ConditionDialog(self, condition=b.condition, device_choices=self._devices)
        if dlg.exec_() == QDialog.Accepted:
            b.condition = dlg.get_condition(); self._refresh()

    def _del(self):
        r = self.lst.currentRow()
        if r >= 0:
            self.branches.pop(r); self._refresh()

    def _move(self, delta):
        r = self.lst.currentRow()
        if r < 0:
            return
        nr = max(0, min(len(self.branches) - 1, r + delta))
        if nr != r:
            self.branches.insert(nr, self.branches.pop(r))
            self._refresh(); self.lst.setCurrentRow(nr)

    def get_ifblock(self) -> IfBlock:
        return IfBlock(branches=self.branches, note=self.note_edit.text().strip())


# ===========================================================================
# Worker chạy kịch bản (nền)
# ===========================================================================

class ScenarioWorker(QThread):
    result_ready = pyqtSignal(object)
    finished_all = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, scenario: Scenario, mock: bool, address_map: dict | None = None,
                 cmd_delay_s: float = 0.1):
        super().__init__()
        self._scn = scenario; self._mock = mock
        self._addr = address_map or {}; self._stop = False
        self._cmd_delay_s = cmd_delay_s

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            runner = ScenarioRunner(mock=self._mock, address_map=self._addr,
                                    on_result=self.result_ready.emit,
                                    stop_flag=lambda: self._stop,
                                    cmd_delay_s=self._cmd_delay_s)
            results = runner.run(self._scn)
            self.finished_all.emit(len(results))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scenario run failed")
            self.failed.emit(str(exc))


# ===========================================================================
# Cửa sổ chính
# ===========================================================================

class ScenarioGridWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FREQ-CAL PRO :: Scenario Builder")
        self.setMinimumSize(1150, 680)
        self.scenario = Scenario(name="Kịch bản mới")
        self.worker: ScenarioWorker | None = None
        self._loading = False
        self._last_results: list[StepResult] = []
        self._last_mode = ""
        self._connected_keys: set[str] = set()
        self.address_map: dict[str, str] = {}
        self.cmd_delay_s: float = 0.1     # nghỉ giữa lệnh khi chạy REAL (mặc định 100ms)

        # ánh xạ runtime (QTreeWidgetItem không hashable -> meta lưu trong item)
        self._id_to_item: dict = {}       # id(node) -> item
        self._item_results: dict = {}     # id(item) -> list[str]

        self._build_ui()
        self._refresh_tree()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Scenario Builder")
        title.setStyleSheet("font-size:16pt; font-weight:bold;")
        head.addWidget(title); head.addStretch()
        root.addLayout(head)

        bar = QHBoxLayout(); bar.setSpacing(6)
        def mkbtn(text, slot, color=None):
            b = QPushButton(text); b.clicked.connect(slot)
            if color:
                b.setStyleSheet(f"background:{color}; color:{Colors.BG_WINDOW}; font-weight:bold;"
                                f" border:none; border-radius:6px; padding:8px 14px;")
            bar.addWidget(b); return b
        mkbtn("🔌 Thiết bị", self._open_device_manager)
        mkbtn("➕ Bước", self._add_step)
        mkbtn("🔁 Loop", self._add_loop)
        mkbtn("❓ If", self._add_if)
        mkbtn("✏ Sửa", self._edit_node)
        mkbtn("⧉ Nhân bản", self._dup_node)
        mkbtn("🗑 Xóa", self._del_node)
        mkbtn("▲", lambda: self._move(-1))
        mkbtn("▼", lambda: self._move(1))
        mkbtn("📖 Tập lệnh", self._open_command_reference)
        bar.addStretch()
        mkbtn("📂 Mở", self._load); mkbtn("💾 Lưu", self._save)
        self.btn_run = mkbtn("▶ CHẠY", self._run, Colors.ACCENT_CYAN)
        self.btn_stop = mkbtn("■ DỪNG", self._stop, Colors.ACCENT_RED); self.btn_stop.setEnabled(False)
        self.btn_export = mkbtn("📤 Xuất", self._export_results); self.btn_export.setEnabled(False)
        root.addLayout(bar)

        self.tree = QTreeWidget()
        self.header = CheckBoxHeader(self.tree, label="Bật / Nội dung")
        self.tree.setHeader(self.header)
        self.tree.setColumnCount(len(COLS))
        self.tree.setHeaderLabels(COLS)
        self.header.toggled_all.connect(self._toggle_all)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_node())
        # Cột 0 (Nội dung) tự dãn lấp chỗ trống; cột 1–4 kéo rộng/hẹp tự do.
        # Tắt "dãn cột cuối" để tránh tranh chấp với cột 0 Stretch -> kéo mượt hơn.
        self.header.setStretchLastSection(False)
        self.header.setMinimumSectionSize(50)          # cột không co về 0, dễ thấy mép
        self.header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLS)):
            self.header.setSectionResizeMode(c, QHeaderView.Interactive)
        self.tree.setColumnWidth(1, 260)   # Mô tả lệnh
        self.tree.setColumnWidth(2, 120)   # Thiết bị
        self.tree.setColumnWidth(3, 190)   # Tham số / Điều kiện
        self.tree.setColumnWidth(4, 200)   # Kết quả
        self.tree.setColumnWidth(5, 90)    # Trạng thái
        root.addWidget(self.tree, 3)

        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(140)
        root.addWidget(self.log, 1)
        self.statusBar().showMessage("Sẵn sàng.")

    # ------------------------------------------------------------------
    # Dựng cây
    # ------------------------------------------------------------------
    def _obj_of(self, item):
        return item.data(0, ROLE_OBJ) if item is not None else None

    def _kind_of(self, item):
        return item.data(0, ROLE_KIND) if item is not None else None

    def _parent_of(self, item):
        return item.data(0, ROLE_PARENT) if item is not None else None

    def _container_of(self, item):
        """List thật trong scenario chứa obj của item (suy ra từ parent_obj)."""
        parent = self._parent_of(item)
        if parent is None:
            return self.scenario.nodes
        if isinstance(parent, LoopBlock):
            return parent.body
        if isinstance(parent, Branch):
            return parent.body
        if isinstance(parent, IfBlock):
            return parent.branches
        return None

    def _refresh_tree(self):
        self._loading = True
        self.tree.clear()
        self._id_to_item.clear(); self._item_results.clear()
        root = self.tree.invisibleRootItem()
        for node in self.scenario.nodes:
            self._add_node_item(node, root, None)
        self.tree.expandAll()
        self._loading = False
        self._update_header_check()
        n = len(self.scenario.nodes)
        self.statusBar().showMessage(f"{n} node cấp ngoài.")

    def _new_item(self, parent, enabled, label, desc="", devices="", param="",
                  kind="step", obj=None, parent_obj=None):
        it = QTreeWidgetItem(parent)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Checked if enabled else Qt.Unchecked)
        it.setText(0, label); it.setText(1, desc)
        it.setText(2, devices); it.setText(3, param)
        fg = QColor(Colors.TEXT_MAIN) if enabled else QColor(Colors.TEXT_DIM)
        for c in range(len(COLS)):
            it.setForeground(c, fg)
        it.setData(0, ROLE_OBJ, obj)
        it.setData(0, ROLE_KIND, kind)
        it.setData(0, ROLE_PARENT, parent_obj)
        if obj is not None:
            self._id_to_item[id(obj)] = it
        return it

    def _add_node_item(self, node, parent_item, parent_obj):
        kind = node_kind(node)
        if kind == "step":
            if node.action == "raw_scpi":
                step_label = node.params.get("__cmd_original__",
                                             node.params.get("__template__", "lệnh thô"))
                step_desc = node.params.get("__cmd_desc__", "")
            else:
                spec = ACTION_SPECS.get(node.action, {})
                step_label = spec.get("label", node.action)
                step_desc = spec.get("desc", "")
            self._new_item(parent_item, node.enabled,
                           f"Bước: {step_label}", step_desc,
                           ", ".join(node.devices) if node.devices else "—",
                           node.describe_params(), "step", node, parent_obj)
        elif kind == "loop":
            it = self._new_item(parent_item, node.enabled,
                                f"🔁 Lặp {node.count} lần" + (f"  — {node.note}" if node.note else ""),
                                "", "", f"{node.count} lần", "loop", node, parent_obj)
            for s in node.body:
                self._add_node_item(s, it, node)
        elif kind == "if":
            it = self._new_item(parent_item, node.enabled,
                                "❓ Rẽ nhánh (If)" + (f"  — {node.note}" if node.note else ""),
                                "", "", f"{len(node.branches)} nhánh", "if", node, parent_obj)
            for i, br in enumerate(node.branches):
                if br.condition is None:
                    lbl = "Ngược lại (ELSE)"
                elif i == 0:
                    lbl = f"Nếu  {br.condition.describe()}"
                else:
                    lbl = f"Ngược lại nếu  {br.condition.describe()}"
                bit = self._new_item(it, br.enabled, lbl, "", "",
                                     br.condition.describe() if br.condition else "", "branch",
                                     br, node)
                for s in br.body:
                    self._add_node_item(s, bit, br)

    # ------------------------------------------------------------------
    # Checkbox bật/tắt
    # ------------------------------------------------------------------
    def _on_item_changed(self, item, column):
        if self._loading or column != 0:
            return
        obj = self._obj_of(item)
        if obj is None:
            return
        enabled = item.checkState(0) == Qt.Checked
        obj.enabled = enabled
        self._loading = True
        fg = QColor(Colors.TEXT_MAIN) if enabled else QColor(Colors.TEXT_DIM)
        for c in range(len(COLS)):
            item.setForeground(c, fg)
        self._loading = False
        self._update_header_check()

    def _set_all_enabled(self, enabled: bool):
        for node in self.scenario.nodes:
            node.enabled = enabled
            if isinstance(node, LoopBlock):
                for s in node.body:
                    s.enabled = enabled
            elif isinstance(node, IfBlock):
                for br in node.branches:
                    br.enabled = enabled
                    for s in br.body:
                        s.enabled = enabled

    def _toggle_all(self, checked: bool):
        self._set_all_enabled(checked)
        self._refresh_tree()

    def _update_header_check(self):
        nodes = self.scenario.nodes
        self.header.setChecked(bool(nodes) and all(getattr(n, "enabled", True) for n in nodes))

    # ------------------------------------------------------------------
    # Tiện ích chọn
    # ------------------------------------------------------------------
    def _sel(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def _ensure_connected(self):
        # Dùng address_map đã cấu hình từ Device Manager — không scan lại VISA bus.
        self._connected_keys = set(self.address_map.keys())

    def _container_for_step(self, item):
        """Trả list để chèn 1 BƯỚC dựa trên item đang chọn (None nếu phải chọn nhánh)."""
        if item is None:
            return self.scenario.nodes
        kind = self._kind_of(item)
        if kind == "step":
            return self._container_of(item)        # cùng cấp với bước đang chọn
        if kind == "loop":
            return self._obj_of(item).body
        if kind == "branch":
            return self._obj_of(item).body
        if kind == "if":
            return None                            # cần chọn một nhánh cụ thể
        return self.scenario.nodes

    def _top_level_container_index(self, item):
        """Tìm vị trí node cấp ngoài chứa item (để chèn Loop/If kề sau)."""
        cur = item
        while cur is not None and cur.parent() is not None:
            cur = cur.parent()
        if cur is None:
            return len(self.scenario.nodes)
        obj = self._obj_of(cur)
        idx = self._index_by_identity(self.scenario.nodes, obj)
        return idx + 1 if idx >= 0 else len(self.scenario.nodes)

    # ------------------------------------------------------------------
    # Thêm / sửa / xóa
    # ------------------------------------------------------------------
    def _add_step(self):
        container = self._container_for_step(self._sel())
        if container is None:
            QMessageBox.information(self, "Chọn nhánh",
                                   "Đang chọn khối If. Hãy chọn một NHÁNH cụ thể để thêm bước vào.")
            return
        self._ensure_connected()
        dlg = StepEditorDialog(self, connected_keys=self._connected_keys)
        if dlg.exec_() == QDialog.Accepted:
            step = dlg.get_step(); step.enabled = False
            container.append(step)
            self._refresh_tree()

    def _add_loop(self):
        dlg = LoopEditorDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            count, note = dlg.get_values()
            loop = LoopBlock(count=count, note=note, enabled=False, body=[])
            self.scenario.add_node(loop, self._top_level_container_index(self._sel()))
            self._refresh_tree()

    def _add_if(self):
        dlg = IfEditorDialog(self, device_choices=self.scenario.all_device_keys() or None)
        if dlg.exec_() == QDialog.Accepted:
            ib = dlg.get_ifblock(); ib.enabled = False
            self.scenario.add_node(ib, self._top_level_container_index(self._sel()))
            self._refresh_tree()

    @staticmethod
    def _index_by_identity(lst, obj) -> int:
        for i, x in enumerate(lst):
            if x is obj:
                return i
        return -1

    def _edit_node(self):
        item = self._sel()
        if item is None:
            return
        kind = self._kind_of(item); obj = self._obj_of(item)
        cont = self._container_of(item)
        if kind == "step":
            self._ensure_connected()
            dlg = StepEditorDialog(self, step=obj, connected_keys=self._connected_keys)
            if dlg.exec_() == QDialog.Accepted:
                new = dlg.get_step(); new.enabled = obj.enabled
                idx = self._index_by_identity(cont, obj)
                if idx >= 0:
                    cont[idx] = new
                self._refresh_tree()
        elif kind == "loop":
            dlg = LoopEditorDialog(self, loop=obj)
            if dlg.exec_() == QDialog.Accepted:
                obj.count, obj.note = dlg.get_values(); self._refresh_tree()
        elif kind == "if":
            dlg = IfEditorDialog(self, ib=obj, device_choices=self.scenario.all_device_keys() or None)
            if dlg.exec_() == QDialog.Accepted:
                new = dlg.get_ifblock(); new.enabled = obj.enabled
                idx = self._index_by_identity(cont, obj)
                if idx >= 0:
                    cont[idx] = new
                self._refresh_tree()
        elif kind == "branch":
            if obj.condition is None:
                QMessageBox.information(self, "ELSE", "Nhánh 'Ngược lại' không có điều kiện để sửa.")
                return
            dlg = ConditionDialog(self, condition=obj.condition,
                                  device_choices=self.scenario.all_device_keys() or None)
            if dlg.exec_() == QDialog.Accepted:
                obj.condition = dlg.get_condition(); self._refresh_tree()

    def _dup_node(self):
        item = self._sel()
        if item is None:
            return
        obj = self._obj_of(item); cont = self._container_of(item); kind = self._kind_of(item)
        idx = self._index_by_identity(cont, obj) if cont is not None else -1
        if idx < 0:
            return
        if kind == "branch":
            clone = Branch.from_dict(obj.to_dict())
        elif kind in ("loop", "if"):
            clone = node_from_dict(obj.to_dict())
        else:
            clone = ScenarioStep.from_dict(obj.to_dict())
        cont.insert(idx + 1, clone)
        self._refresh_tree()

    def _del_node(self):
        item = self._sel()
        if item is None:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một dòng để xóa."); return
        obj = self._obj_of(item); cont = self._container_of(item)
        idx = self._index_by_identity(cont, obj) if cont is not None else -1
        if idx < 0:
            return
        cont.pop(idx)
        self._refresh_tree()

    def _move(self, delta):
        item = self._sel()
        if item is None:
            return
        obj = self._obj_of(item); cont = self._container_of(item)
        i = self._index_by_identity(cont, obj) if cont is not None else -1
        if i < 0:
            return
        j = max(0, min(len(cont) - 1, i + delta))
        if j != i:
            cont.insert(j, cont.pop(i)); self._refresh_tree()

    def _log(self, msg, color=Colors.TEXT_DIM):
        self.log.append(f"<font color='{color}'>{msg}</font>")

    # ------------------------------------------------------------------
    # Device manager / lưu / mở
    # ------------------------------------------------------------------
    def _open_command_reference(self):
        from gui.command_reference import CommandReferenceDialog
        dlg = CommandReferenceDialog(self)
        dlg.exec_()

    def _open_device_manager(self):
        from gui.device_manager import DeviceManagerDialog
        from core.profile import ConnectionProfile
        prof = getattr(self, "_profile", ConnectionProfile())
        dlg = DeviceManagerDialog(self, mock=False, profile=prof)
        if dlg.exec_() == QDialog.Accepted:
            self._profile = dlg.get_profile()
            self.address_map = self._profile.address_map()
            self._connected_keys = set(self.address_map.keys())
            self.cmd_delay_s = self._profile.cmd_delay_ms / 1000.0
            self._log(f"Đã cấu hình {len(self.address_map)} thiết bị: "
                      f"{', '.join(self.address_map) or '(trống)'} "
                      f"| delay giữa lệnh: {self._profile.cmd_delay_ms}ms",
                      Colors.ACCENT_GREEN)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Lưu kịch bản", "scenario.json", "JSON (*.json)")
        if path:
            self.scenario.save_json(path); self._log(f"Đã lưu: {path}", Colors.ACCENT_GREEN)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở kịch bản", "", "JSON (*.json)")
        if not path:
            return
        try:
            self.scenario = Scenario.load_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi mở file", str(exc)); return
        self._refresh_tree(); self._log(f"Đã mở: {path}", Colors.ACCENT_GREEN)

    # ------------------------------------------------------------------
    # Chạy
    # ------------------------------------------------------------------
    def _run(self):
        problems = validate_scenario(self.scenario)
        if problems:
            QMessageBox.warning(self, "Kịch bản chưa hợp lệ", "\n".join(problems[:12])); return

        self._item_results.clear()
        self._last_results = []
        self.btn_export.setEnabled(False)
        self._loading = True
        for it in self._all_items():
            it.setText(4, ""); it.setText(5, "")   # xóa Kết quả + Trạng thái
        self._loading = False

        mock = False                       # đã bỏ MOCK — luôn chạy với thiết bị thật
        need = self.scenario.all_device_keys()
        missing = [d for d in need if d not in self.address_map]
        if missing:
            QMessageBox.warning(self, "Thiếu địa chỉ thiết bị",
                                "Cần gán địa chỉ cho:\n  " + ", ".join(missing)
                                + "\n\nBấm '🔌 Thiết bị' để quét & gán.")
            return

        self.btn_run.setEnabled(False); self.btn_stop.setEnabled(True)
        self._last_mode = "REAL"
        self._log(f"--- Bắt đầu chạy ({self._last_mode}) ---", Colors.ACCENT_CYAN)
        self.worker = ScenarioWorker(self.scenario, mock=mock, address_map=self.address_map,
                                     cmd_delay_s=self.cmd_delay_s)
        self.worker.result_ready.connect(self._on_result)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _stop(self):
        if self.worker:
            self.worker.request_stop(); self._log("Đã yêu cầu dừng...", Colors.ACCENT_WARN)

    def _all_items(self):
        out = []
        def walk(parent):
            for i in range(parent.childCount()):
                ch = parent.child(i); out.append(ch); walk(ch)
        walk(self.tree.invisibleRootItem())
        return out

    def _on_result(self, res: StepResult):
        self._last_results.append(res)
        item = self._id_to_item.get(res.node_id)
        if item is None:
            self._log(f"B{res.step_index} {res.summary()}",
                      Colors.ACCENT_RED if not res.ok else Colors.TEXT_DIM)
            return
        self._loading = True
        key = id(item)
        self._item_results.setdefault(key, []).append(res.result_cell())
        # Bỏ ô trống (lệnh ghi) + gộp giá trị trùng LIÊN TIẾP cho gọn.
        collapsed = []
        for c in self._item_results[key]:
            if c and (not collapsed or collapsed[-1] != c):
                collapsed.append(c)
        item.setText(4, "  |  ".join(collapsed))   # cột Kết quả
        if res.kind != "control":
            any_err = any("LỖI" in s for s in self._item_results[key])
            item.setText(5, "LỖI" if any_err else "OK")          # cột Trạng thái
            item.setForeground(5, QColor(Colors.ACCENT_RED if any_err else Colors.ACCENT_GREEN))
        self._loading = False
        self._log(f"B{res.step_index} {res.summary()}",
                  Colors.ACCENT_RED if not res.ok else Colors.ACCENT_GREEN)

    def _on_finished(self, total):
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)
        self.btn_export.setEnabled(bool(self._last_results))
        self._log(f"--- Hoàn tất: {total} kết quả ---", Colors.ACCENT_CYAN)
        self.statusBar().showMessage(f"Hoàn tất: {total} kết quả.")

    def _on_failed(self, msg):
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)
        self._log(f"LỖI: {msg}", Colors.ACCENT_RED)
        QMessageBox.critical(self, "Lỗi chạy kịch bản", msg)

    def _export_results(self):
        if not self._last_results:
            QMessageBox.information(self, "Chưa có dữ liệu", "Hãy chạy kịch bản trước khi xuất."); return
        from core import scenario_export as sx
        path, _ = QFileDialog.getSaveFileName(self, "Xuất kết quả", "ket_qua_kich_ban.xlsx",
                                              "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        meta = {"scenario": self.scenario.name, "mode": self._last_mode,
                "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        try:
            out = sx.export(self._last_results, path, meta=meta)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi xuất file", str(exc)); return
        self._log(f"Đã xuất: {out}", Colors.ACCENT_GREEN)
        QMessageBox.information(self, "Xong", f"Đã xuất kết quả:\n{out}")


def run_scenario_builder():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_global_qss())
    win = ScenarioGridWindow()
    win.show()
    app.exec_()


if __name__ == "__main__":
    run_scenario_builder()
