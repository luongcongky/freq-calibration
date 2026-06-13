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
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPointF
from PyQt5.QtGui import QColor, QFont, QPainter, QPolygonF

from drivers import DEVICE_REGISTRY
from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    ACTION_SPECS, OPERATORS, OP_LABELS, MAX_NEST_DEPTH,
    actions_for_devices, validate_scenario, node_kind, node_from_dict,
)
from core.scenario_runner import ScenarioRunner, StepResult
from core.commands import (
    parse_cmd, get_commands_for, get_common_commands, load_custom, WAIT_CMD, BREAK_CMD,
)

logger = logging.getLogger(__name__)

from gui.theme import Colors, build_global_qss
from gui.widgets import ThemeToggle, EXPR_HELP

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
# Tree: luôn hiện icon expand/collapse cho item có con (không chỉ khi hover)
# ===========================================================================

class ScenarioTree(QTreeWidget):
    items_dropped = pyqtSignal(list, object, int)   # dragged_items, target_or_None, indicator

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        target = self.itemAt(event.pos())
        indicator = int(self.dropIndicatorPosition())
        dragged = list(self.selectedItems())
        if dragged:
            event.accept()
            self.items_dropped.emit(dragged, target, indicator)
        else:
            event.ignore()

    def drawBranches(self, painter, rect, index):
        # KHÔNG gọi super() để tránh chevron mặc định (chỉ hiện khi hover trên
        # Windows). Tự vẽ tam giác cho mọi node có con -> luôn hiển thị.
        if index.isValid() and self.model().hasChildren(index):
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(Colors.TEXT_DIM))
            cx = rect.right() - 11
            cy = rect.center().y()
            s = 4.0
            if self.isExpanded(index):                         # ▼ đang mở
                pts = [QPointF(cx - s, cy - s + 1), QPointF(cx + s, cy - s + 1),
                       QPointF(cx, cy + s - 1)]
            else:                                              # ▶ đang đóng
                pts = [QPointF(cx - s + 1, cy - s), QPointF(cx - s + 1, cy + s),
                       QPointF(cx + s - 1, cy)]
            painter.drawPolygon(QPolygonF(pts))
            painter.restore()


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

        # Chọn loại bước: lệnh thiết bị (SCPI) hoặc biến/tính toán.
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Loại bước:"))
        self.step_mode = QComboBox()
        self.step_mode.addItem("Lệnh thiết bị (SCPI)", "device")
        self.step_mode.addItem("Biến / Tính toán", "var")
        self.step_mode.currentIndexChanged.connect(self._update_mode)
        mode_row.addWidget(self.step_mode, 1)
        root.addLayout(mode_row)

        # ----- Panel lệnh thiết bị -----
        self.device_panel = QWidget()
        dp = QVBoxLayout(self.device_panel); dp.setContentsMargins(0, 0, 0, 0); dp.setSpacing(6)
        dp.addWidget(QLabel("Thiết bị (chọn 1 hoặc nhiều — chạy cùng bước):"))
        dp.addWidget(QLabel("🟢 = đang kết nối   ·   ○ = chưa thấy"))
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
        dp.addWidget(self.dev_list)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Lệnh:"))
        self.cmd_search = QLineEdit()
        self.cmd_search.setPlaceholderText("Tìm lệnh…")
        self.cmd_search.textChanged.connect(self._filter_commands)
        search_row.addWidget(self.cmd_search)
        dp.addLayout(search_row)

        self.cmd_list = QListWidget()
        self.cmd_list.setMinimumHeight(160)
        self.cmd_list.setStyleSheet(
            f"QListWidget::item:selected {{ background:{Colors.ACCENT_CYAN};"
            f" color:{Colors.BG_WINDOW}; }}"
        )
        self.cmd_list.currentItemChanged.connect(self._on_cmd_selected)
        dp.addWidget(self.cmd_list)

        self.cmd_info = QLabel("")
        self.cmd_info.setWordWrap(True)
        self.cmd_info.setStyleSheet("color: #a0a5ad; font-size: 11px;")
        dp.addWidget(self.cmd_info)

        self.param_form = QFormLayout()
        dp.addLayout(self.param_form)
        root.addWidget(self.device_panel)

        # ----- Panel biến / tính toán -----
        self.var_panel = QWidget()
        vform = QFormLayout(self.var_panel); vform.setContentsMargins(0, 0, 0, 0)
        self.var_action = QComboBox()
        self.var_action.addItem("Gán biến (set_var)", "set_var")
        self.var_action.addItem("Tính toán → biến (compute)", "compute")
        self.var_action.addItem("Thu thập vào list (collect)", "collect")
        vform.addRow("Thao tác:", self.var_action)
        self.var_name = QLineEdit(); self.var_name.setPlaceholderText("vd: error / samples")
        vform.addRow("Tên biến / list:", self.var_name)
        self.var_expr = QLineEdit()
        self.var_expr.setPlaceholderText("vd: avg(samples) · abs(f_avg-f_set)/f_set · $last")
        self.var_expr.setToolTip(EXPR_HELP)
        vform.addRow("Biểu thức / nguồn:", self.var_expr)
        hint = QLabel("Hàm: avg, mean, std, min, max, abs, sqrt, count, last · biến đặc biệt: $last, $iter")
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;"); hint.setWordWrap(True)
        vform.addRow("", hint)
        root.addWidget(self.var_panel)

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
        self._update_mode()

    # ── helpers ────────────────────────────────────────────────────────────

    def _update_mode(self):
        is_var = self.step_mode.currentData() == "var"
        self.device_panel.setVisible(not is_var)
        self.var_panel.setVisible(is_var)

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
        self._add_cmd_item(BREAK_CMD, "__break__")

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
                w.setPlaceholderText("số hoặc =biến")
                w.setToolTip("Nhập số cố định (vd: 1000) hoặc =tên_biến / =biểu_thức (vd: =freq_start, =freq_start*2)")
            label = p.label + (f" ({p.unit})" if p.unit else "") + ":"
            self.param_form.addRow(label, w)
            self._param_widgets[p.name] = w

    # ── load existing step ──────────────────────────────────────────────────

    def _load_step(self, step: ScenarioStep):
        if step.action in ("set_var", "compute", "collect"):
            self.step_mode.setCurrentIndex(max(0, self.step_mode.findData("var")))
            self.var_action.setCurrentIndex(max(0, self.var_action.findData(step.action)))
            if step.action == "collect":
                self.var_name.setText(step.params.get("var", ""))
                self.var_expr.setText(step.params.get("source", "$last"))
            else:
                self.var_name.setText(step.params.get("name") or step.params.get("target", ""))
                self.var_expr.setText(step.params.get("expr", ""))
            self.note_edit.setText(step.note)
            return

        for i in range(self.dev_list.count()):
            it = self.dev_list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in step.devices else Qt.Unchecked)
        self._refresh_commands()

        if step.action == "wait":
            self._select_by_model_key("__wait__")
            w = self._param_widgets.get("seconds")
            if isinstance(w, QLineEdit):
                w.setText(str(step.params.get("seconds", 0.5)))
        elif step.action == "break":
            self._select_by_model_key("__break__")
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
        note = self.note_edit.text().strip()

        # --- Chế độ Biến / Tính toán ---
        if self.step_mode.currentData() == "var":
            act = self.var_action.currentData()
            name = self.var_name.text().strip()
            expr = self.var_expr.text().strip()
            if not name:
                QMessageBox.warning(self, "Thiếu", "Nhập tên biến / list."); return
            if act == "collect":
                params = {"var": name, "source": expr or "$last"}
            else:
                if not expr:
                    QMessageBox.warning(self, "Thiếu", "Nhập biểu thức."); return
                params = {"name": name, "expr": expr}
            self._result = ScenarioStep(action=act, devices=[], params=params, note=note)
            self.accept()
            return

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

        if model_key == "__break__":
            self._result = ScenarioStep(action="break", devices=[], params={}, note=note)
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
                if raw.startswith("="):
                    params[p.name] = raw  # runtime sẽ eval qua _resolve_params
                elif p.ptype == "int":
                    try:
                        params[p.name] = int(float(raw))
                    except ValueError:
                        QMessageBox.warning(self, "Sai tham số",
                                            f"'{p.label}' phải là số nguyên hoặc =biểu_thức."); return
                else:
                    try:
                        params[p.name] = float(raw)
                    except ValueError:
                        QMessageBox.warning(self, "Sai tham số",
                                            f"'{p.label}' phải là số hoặc =biểu_thức."); return

        self._result = ScenarioStep(action="raw_scpi", devices=devices, params=params, note=note)
        self.accept()

    def get_step(self) -> ScenarioStep:
        return self._result


# ===========================================================================
# Dialog: soạn Loop
# ===========================================================================

class LoopEditorDialog(QDialog):
    def __init__(self, parent=None, loop: LoopBlock | None = None,
                 device_choices: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Soạn vòng lặp (Loop)")
        self.setMinimumWidth(420)
        self._devices = device_choices or list(DEVICE_REGISTRY.keys())
        self._condition = loop.condition if (loop and loop.condition) else None
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.mode = QComboBox()
        self.mode.addItem("Lặp số lần cố định", "count")
        self.mode.addItem("Lặp đến khi điều kiện đúng (Until)", "until")
        self.mode.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Kiểu lặp:", self.mode)

        self.spin = QSpinBox(); self.spin.setRange(1, 1000000); self.spin.setValue(2)
        form.addRow("Số lần lặp:", self.spin)

        self.max_iter = QSpinBox(); self.max_iter.setRange(1, 1000000); self.max_iter.setValue(50)
        form.addRow("Tối đa (max_iter):", self.max_iter)

        cond_row = QHBoxLayout()
        self.cond_lbl = QLabel("(chưa đặt)")
        self.cond_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        btn_cond = QPushButton("Đặt điều kiện dừng…"); btn_cond.clicked.connect(self._edit_cond)
        cond_row.addWidget(self.cond_lbl, 1); cond_row.addWidget(btn_cond)
        form.addRow("Điều kiện dừng:", cond_row)

        self.note = QLineEdit()
        form.addRow("Ghi chú:", self.note)
        root.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        if loop is not None:
            self.mode.setCurrentIndex(max(0, self.mode.findData(getattr(loop, "mode", "count"))))
            self.spin.setValue(loop.count); self.note.setText(loop.note)
            self.max_iter.setValue(getattr(loop, "max_iter", 50))
        self._refresh_cond(); self._update_visibility()

    def _refresh_cond(self):
        self.cond_lbl.setText(self._condition.describe() if self._condition else "(chưa đặt)")

    def _edit_cond(self):
        dlg = ConditionDialog(self, condition=self._condition, device_choices=self._devices)
        if dlg.exec_() == QDialog.Accepted:
            self._condition = dlg.get_condition(); self._refresh_cond()

    def _update_visibility(self):
        until = self.mode.currentData() == "until"
        self.spin.setEnabled(not until)
        self.max_iter.setEnabled(until)
        self.cond_lbl.setEnabled(until)

    def _on_accept(self):
        if self.mode.currentData() == "until" and self._condition is None:
            QMessageBox.warning(self, "Thiếu", "Loop 'đến khi' cần điều kiện dừng."); return
        self.accept()

    def get_loop(self) -> LoopBlock:
        return LoopBlock(
            count=self.spin.value(), note=self.note.text().strip(),
            mode=self.mode.currentData(),
            condition=self._condition if self.mode.currentData() == "until" else None,
            max_iter=self.max_iter.value(),
        )


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

        self._form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("So sánh giá trị đo gần nhất", "measure")
        self.kind.addItem("Biểu thức (vd: error)", "expr")
        self.kind.addItem("Theo trạng thái bước trước (OK/Lỗi)", "status")
        self.kind.currentIndexChanged.connect(self._update_visibility)
        self._form.addRow("Loại điều kiện:", self.kind)

        self.device = QComboBox()
        self.device.addItem("(đo gần nhất — bất kỳ)", "")
        for k in (device_choices or list(DEVICE_REGISTRY.keys())):
            self.device.addItem(k, k)
        self._form.addRow("Thiết bị nguồn:", self.device)

        self.expr = QLineEdit()
        self.expr.setPlaceholderText("vd: error  hoặc  abs(f_avg - f_set)/f_set")
        self._form.addRow("Biểu thức:", self.expr)

        self.op = QComboBox()
        for o in OPERATORS:
            self.op.addItem(f"{o}  ({OP_LABELS[o]})", o)
        self.op.currentIndexChanged.connect(self._update_visibility)
        self._form.addRow("Toán tử:", self.op)

        self.val = QLineEdit("0")
        self._form.addRow("Ngưỡng:", self.val)
        self.val2 = QLineEdit("0")
        self._form.addRow("Ngưỡng 2 (khoảng):", self.val2)

        self.status = QComboBox()
        self.status.addItem("OK", "ok"); self.status.addItem("LỖI", "error")
        self._form.addRow("Trạng thái:", self.status)
        root.addLayout(self._form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        if condition is not None:
            self._load(condition)
        self._update_visibility()

    def _load(self, c: Condition):
        self.kind.setCurrentIndex(max(0, self.kind.findData(c.kind)))
        self.device.setCurrentIndex(max(0, self.device.findData(c.device)))
        self.expr.setText(c.expr)
        self.op.setCurrentIndex(max(0, self.op.findData(c.op)))
        self.val.setText(str(c.value)); self.val2.setText(str(c.value2))
        self.status.setCurrentIndex(self.status.findData(c.status))

    def _show_row(self, widget, visible: bool):
        widget.setVisible(visible)
        lbl = self._form.labelForField(widget)
        if lbl:
            lbl.setVisible(visible)

    def _update_visibility(self):
        kind = self.kind.currentData()
        is_measure = kind == "measure"
        is_expr = kind == "expr"
        is_cmp = is_measure or is_expr
        self._show_row(self.device, is_measure)
        self._show_row(self.expr, is_expr)
        self._show_row(self.op, is_cmp)
        self._show_row(self.val, is_cmp)
        self._show_row(self.val2, is_cmp and self.op.currentData() in ("between", "outside"))
        self._show_row(self.status, kind == "status")
        self.adjustSize()

    def _on_accept(self):
        kind = self.kind.currentData()
        if kind in ("measure", "expr"):
            try:
                v = float(self.val.text().strip()); v2 = float(self.val2.text().strip() or 0)
            except ValueError:
                QMessageBox.warning(self, "Sai", "Ngưỡng phải là số."); return
            if kind == "expr" and not self.expr.text().strip():
                QMessageBox.warning(self, "Thiếu", "Nhập biểu thức điều kiện."); return
            self._result = Condition(
                kind=kind, device=self.device.currentData(),
                expr=self.expr.text().strip(),
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
        self.lst.itemDoubleClicked.connect(lambda *_: self._edit_cond())   # sửa = double-click
        root.addWidget(self.lst)

        bar = QHBoxLayout()
        for text, slot in [("➕ Thêm điều kiện", self._add_cond),
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
        self.resize(1600, 900)
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
        # Switch chuyển theme ở góc trên phải.
        self.theme_toggle = ThemeToggle(left="Classic", right="Digital", checked=False)
        self.theme_toggle.toggled.connect(
            lambda checked: self._switch_to_digital() if checked else None)
        head.addWidget(self.theme_toggle)
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

        self.tree = ScenarioTree()
        self.header = CheckBoxHeader(self.tree, label="Bật / Nội dung")
        self.tree.setHeader(self.header)
        self.tree.setColumnCount(len(COLS))
        self.tree.setHeaderLabels(COLS)
        self.header.toggled_all.connect(self._toggle_all)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)  # chọn nhiều dòng (Ctrl/Shift)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_node())
        self.tree.items_dropped.connect(self._on_items_dropped)
        # Cột 0 (Nội dung) tự dãn lấp chỗ trống; cột 1–4 kéo rộng/hẹp tự do.
        # Tắt "dãn cột cuối" để tránh tranh chấp với cột 0 Stretch -> kéo mượt hơn.
        self.header.setStretchLastSection(False)
        self.header.setMinimumSectionSize(50)          # cột không co về 0, dễ thấy mép
        self.header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLS)):
            self.header.setSectionResizeMode(c, QHeaderView.Interactive)
        self.tree.setColumnWidth(1, 410)   # Mô tả lệnh (+50; cột Nội dung stretch tự co)
        self.tree.setColumnWidth(2, 120)   # Thiết bị
        self.tree.setColumnWidth(3, 190)   # Tham số / Điều kiện
        self.tree.setColumnWidth(4, 250)   # Kết quả (+50)
        self.tree.setColumnWidth(5, 90)    # Trạng thái
        root.addWidget(self.tree, 3)

        log_head = QHBoxLayout()
        log_head.addWidget(QLabel("Log"))
        log_head.addStretch()
        btn_clear_log = QPushButton("🗑 Xóa log")
        btn_clear_log.clicked.connect(lambda: self.log.clear())
        log_head.addWidget(btn_clear_log)
        root.addLayout(log_head)

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
        flags = it.flags() | Qt.ItemIsUserCheckable
        if kind in ("step", "loop", "if"):
            flags |= Qt.ItemIsDragEnabled
        if kind in ("loop", "branch"):
            flags |= Qt.ItemIsDropEnabled   # cho phép thả VÀO bên trong
        it.setFlags(flags)
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
            elif node.action in ("set_var", "compute", "collect"):
                spec = ACTION_SPECS.get(node.action, {})
                step_label = spec.get("label", node.action)
                step_desc = node.note          # bước Biến/Tính toán: Mô tả lệnh = Ghi chú
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
        if self._kind_of(item) in ("loop", "if"):
            self._cascade_check(item, enabled)
        self._loading = False
        self._update_header_check()

    def _cascade_check(self, parent_item, enabled):
        state = Qt.Checked if enabled else Qt.Unchecked
        fg = QColor(Colors.TEXT_MAIN) if enabled else QColor(Colors.TEXT_DIM)
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            child_obj = self._obj_of(child)
            if child_obj is not None:
                child_obj.enabled = enabled
            for c in range(len(COLS)):
                child.setForeground(c, fg)
            self._cascade_check(child, enabled)

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

    def _resolve_insert(self, item):
        """Trả (container, vị_trí) để chèn 1 node theo item đang chọn — chèn vào
        ĐÚNG cấp (thân Loop / nhánh If / cùng cấp bước). None nếu phải chọn nhánh."""
        container = self._container_for_step(item)
        if container is None:
            return None, None
        if item is not None and self._kind_of(item) == "step":
            idx = self._index_by_identity(container, self._obj_of(item))
            insert_at = idx + 1 if idx >= 0 else len(container)
        else:
            insert_at = len(container)
        return container, insert_at

    def _container_block_depth(self, item) -> int:
        """Số khối Loop/If bao quanh CONTAINER mà item phân giải tới (để biết độ
        sâu sẽ chèn). Node chèn vào sẽ ở độ sâu = giá trị này + 1."""
        kind = self._kind_of(item) if item is not None else None
        if kind == "loop":
            start = item                 # chèn vào thân Loop -> Loop tính 1 cấp
        elif item is not None:
            start = item.parent()        # bước: cùng cấp; nhánh: lên If
        else:
            start = None
        depth, cur = 0, start
        while cur is not None:
            if self._kind_of(cur) in ("loop", "if"):
                depth += 1
            cur = cur.parent()
        return depth

    # ------------------------------------------------------------------
    # Thêm / sửa / xóa
    # ------------------------------------------------------------------
    def _need_branch_msg(self):
        QMessageBox.information(self, "Chọn nhánh",
                               "Đang chọn khối If. Hãy chọn một NHÁNH cụ thể để thêm vào.")

    def _add_step(self):
        item = self._sel()
        container, insert_at = self._resolve_insert(item)
        if container is None:
            self._need_branch_msg(); return
        self._ensure_connected()
        dlg = StepEditorDialog(self, connected_keys=self._connected_keys)
        if dlg.exec_() == QDialog.Accepted:
            step = dlg.get_step(); step.enabled = False
            container.insert(insert_at, step)
            self._refresh_tree()

    def _add_block(self, item, build_block):
        """Chèn 1 khối Loop/If vào đúng cấp theo item đang chọn (cho phép LỒNG)."""
        container, insert_at = self._resolve_insert(item)
        if container is None:
            self._need_branch_msg(); return False
        if self._container_block_depth(item) + 1 > MAX_NEST_DEPTH:
            QMessageBox.warning(self, "Lồng quá sâu",
                                f"Chỉ cho phép lồng tối đa {MAX_NEST_DEPTH} cấp khối.")
            return False
        block = build_block()
        if block is None:
            return False
        block.enabled = False
        container.insert(insert_at, block)
        self._refresh_tree()
        return True

    def _add_loop(self):
        def build():
            dlg = LoopEditorDialog(self, device_choices=self.scenario.all_device_keys() or None)
            return dlg.get_loop() if dlg.exec_() == QDialog.Accepted else None
        self._add_block(self._sel(), build)

    def _add_if(self):
        def build():
            dlg = IfEditorDialog(self, device_choices=self.scenario.all_device_keys() or None)
            return dlg.get_ifblock() if dlg.exec_() == QDialog.Accepted else None
        self._add_block(self._sel(), build)

    # ------------------------------------------------------------------
    # Bọc nhóm lệnh đang chọn vào Loop / If
    # ------------------------------------------------------------------
    def _wrap_selected(self, build_wrapper):
        """Bọc các item đang chọn (phải cùng container) vào một khối mới.
        build_wrapper(body_nodes) -> khối hoặc None nếu hủy."""
        items = self._target_items()
        if not items:
            QMessageBox.information(self, "Chưa chọn",
                                    "Hãy chọn (bôi đen) ít nhất 1 bước để bọc.")
            return
        # Bỏ qua con nếu cha cũng được chọn (con sẽ bị bọc cùng cha).
        ids = {id(it) for it in items}
        top_items = []
        for item in items:
            cur = item.parent()
            shadowed = False
            while cur is not None:
                if id(cur) in ids:
                    shadowed = True; break
                cur = cur.parent()
            if not shadowed:
                top_items.append(item)
        if not top_items:
            return
        # Không cho bọc nhánh branch (If/Else) vào block khác.
        if any(self._kind_of(it) == "branch" for it in top_items):
            QMessageBox.warning(self, "Không hỗ trợ",
                                "Không thể bọc nhánh If/Else vào khối Loop hoặc If.")
            return
        # Tất cả phải cùng container.
        first_cont = self._container_of(top_items[0])
        if first_cont is None or any(self._container_of(it) is not first_cont
                                     for it in top_items):
            QMessageBox.warning(self, "Khác cấp",
                                "Các bước được chọn phải cùng một cấp (cùng container).")
            return
        # Kiểm tra độ sâu lồng.
        if self._container_block_depth(top_items[0]) + 1 > MAX_NEST_DEPTH:
            QMessageBox.warning(self, "Lồng quá sâu",
                                f"Chỉ cho phép lồng tối đa {MAX_NEST_DEPTH} cấp khối.")
            return
        # Lấy (index, obj) rồi sắp theo index tăng dần.
        items_indexed = []
        for it in top_items:
            obj = self._obj_of(it)
            idx = self._index_by_identity(first_cont, obj)
            if idx >= 0:
                items_indexed.append((idx, obj))
        if not items_indexed:
            return
        items_indexed.sort(key=lambda x: x[0])
        body_nodes = [obj for _, obj in items_indexed]
        insert_at = items_indexed[0][0]
        # Hiện dialog và tạo block.
        block = build_wrapper(body_nodes)
        if block is None:
            return
        # Xóa các node gốc (giảm dần để không lệch index).
        for idx, _ in sorted(items_indexed, key=lambda x: x[0], reverse=True):
            first_cont.pop(idx)
        first_cont.insert(insert_at, block)
        self._refresh_tree()

    def _wrap_loop(self):
        def build(body_nodes):
            dlg = LoopEditorDialog(self,
                                   device_choices=self.scenario.all_device_keys() or None)
            if dlg.exec_() != QDialog.Accepted:
                return None
            loop = dlg.get_loop()
            loop.body = body_nodes
            return loop
        self._wrap_selected(build)

    def _wrap_if(self):
        def build(body_nodes):
            dlg = IfEditorDialog(self,
                                 device_choices=self.scenario.all_device_keys() or None)
            if dlg.exec_() != QDialog.Accepted:
                return None
            ib = dlg.get_ifblock()
            # Đưa các bước được chọn vào nhánh đầu tiên (IF).
            if ib.branches:
                ib.branches[0].body = body_nodes
            return ib
        self._wrap_selected(build)

    # ------------------------------------------------------------------
    # Kéo – thả (drag & drop)
    # ------------------------------------------------------------------
    def _on_items_dropped(self, dragged_qt_items, target_qt_item, indicator):
        AboveItem, BelowItem, OnItem, OnViewport = 0, 1, 2, 3

        # Bỏ con nếu cha cũng được kéo; bỏ branch (không cho kéo nhánh).
        ids = {id(it) for it in dragged_qt_items}
        top_items = []
        for item in dragged_qt_items:
            if self._kind_of(item) == "branch":
                continue
            cur = item.parent()
            shadowed = False
            while cur is not None:
                if id(cur) in ids:
                    shadowed = True; break
                cur = cur.parent()
            if not shadowed:
                top_items.append(item)

        if not top_items:
            self._refresh_tree(); return

        # Xác định container đích và vị trí chèn.
        if indicator == OnViewport or target_qt_item is None:
            dest_cont = self.scenario.nodes
            dest_idx = len(dest_cont)
        elif indicator == OnItem:
            target_kind = self._kind_of(target_qt_item)
            if target_kind == "loop":
                dest_cont = self._obj_of(target_qt_item).body
                dest_idx = len(dest_cont)
            elif target_kind == "branch":
                dest_cont = self._obj_of(target_qt_item).body
                dest_idx = len(dest_cont)
            else:
                self._refresh_tree(); return
        else:  # AboveItem / BelowItem
            target_kind = self._kind_of(target_qt_item)
            if target_kind == "branch":
                self._refresh_tree(); return      # không cho sắp xếp lại nhánh kiểu này
            dest_cont = self._container_of(target_qt_item)
            if dest_cont is None:
                self._refresh_tree(); return
            target_obj = self._obj_of(target_qt_item)
            target_idx = self._index_by_identity(dest_cont, target_obj)
            if target_idx < 0:
                self._refresh_tree(); return
            dest_idx = target_idx if indicator == AboveItem else target_idx + 1

        # Thu thập (container_nguồn, index, obj) theo thứ tự của top_items.
        sources = []
        for it in top_items:
            obj = self._obj_of(it); cont = self._container_of(it)
            if obj is None or cont is None:
                continue
            idx = self._index_by_identity(cont, obj)
            if idx >= 0:
                sources.append((cont, idx, obj))

        if not sources:
            self._refresh_tree(); return

        # Chặn thả vào chính hậu duệ của mình.
        for _, _, obj in sources:
            if self._cont_is_inside(dest_cont, obj):
                self._refresh_tree(); return

        # Điều chỉnh dest_idx nếu xóa item trước nó trong cùng container.
        removed_before = sum(1 for cont, idx, _ in sources
                             if cont is dest_cont and idx < dest_idx)
        dest_idx = max(0, dest_idx - removed_before)

        # Xóa nguồn (nhóm theo container, giảm dần).
        by_cont: dict = {}
        for cont, idx, obj in sources:
            by_cont.setdefault(id(cont), []).append((idx, obj, cont))
        for group in by_cont.values():
            group.sort(key=lambda x: x[0], reverse=True)
            for idx, _, cont in group:
                cont.pop(idx)

        # Chèn vào đích theo thứ tự gốc.
        for i, (_, _, obj) in enumerate(sources):
            dest_cont.insert(dest_idx + i, obj)

        self._refresh_tree()

    def _cont_is_inside(self, cont, node) -> bool:
        """True nếu cont là một container lồng bên trong cây con của node."""
        if isinstance(node, LoopBlock):
            if node.body is cont:
                return True
            return any(self._cont_is_inside(cont, c) for c in node.body
                       if isinstance(c, (LoopBlock, IfBlock)))
        if isinstance(node, IfBlock):
            for br in node.branches:
                if br.body is cont:
                    return True
                if any(self._cont_is_inside(cont, c) for c in br.body
                       if isinstance(c, (LoopBlock, IfBlock))):
                    return True
        return False

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
            dlg = LoopEditorDialog(self, loop=obj,
                                   device_choices=self.scenario.all_device_keys() or None)
            if dlg.exec_() == QDialog.Accepted:
                nl = dlg.get_loop()
                obj.count, obj.note = nl.count, nl.note
                obj.mode, obj.condition, obj.max_iter = nl.mode, nl.condition, nl.max_iter
                self._refresh_tree()
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
        items = self._target_items()
        if not items:
            return
        # Bỏ qua item con nếu item cha cũng đang được nhân bản (con sẽ được clone cùng cha).
        ids = {id(it) for it in items}
        to_dup = []
        for item in items:
            cur = item.parent()
            shadowed = False
            while cur is not None:
                if id(cur) in ids:
                    shadowed = True
                    break
                cur = cur.parent()
            if not shadowed:
                to_dup.append(item)
        if not to_dup:
            return
        # Gom theo container, sắp xếp index giảm dần để insert không làm lệch chỉ số.
        groups: dict = {}
        for item in to_dup:
            obj = self._obj_of(item); cont = self._container_of(item); kind = self._kind_of(item)
            if cont is None or obj is None:
                continue
            idx = self._index_by_identity(cont, obj)
            if idx < 0:
                continue
            groups.setdefault(id(cont), []).append((idx, obj, kind, cont))
        for group in groups.values():
            group.sort(key=lambda x: x[0], reverse=True)
            for idx, obj, kind, cont in group:
                if kind == "branch":
                    clone = Branch.from_dict(obj.to_dict())
                elif kind in ("loop", "if"):
                    clone = node_from_dict(obj.to_dict())
                else:
                    clone = ScenarioStep.from_dict(obj.to_dict())
                cont.insert(idx + 1, clone)
        self._refresh_tree()

    def _target_items(self) -> list:
        """Mục để thao tác (di chuyển/xóa): các DÒNG ĐANG CHỌN (highlight).
        Hỗ trợ chọn nhiều dòng bằng Ctrl/Shift. KHÔNG dùng trạng thái checkbox."""
        return list(self.tree.selectedItems())

    def _del_node(self):
        items = self._target_items()
        if not items:
            QMessageBox.information(self, "Chưa chọn",
                                   "Hãy chọn (bôi đen) 1 hoặc nhiều dòng rồi bấm Xóa.")
            return
        # Bỏ qua item con nếu item cha cũng đang bị xóa (tránh xóa 2 lần).
        ids = {id(it) for it in items}
        to_delete = []
        for item in items:
            cur = item.parent()
            shadowed = False
            while cur is not None:
                if id(cur) in ids:
                    shadowed = True
                    break
                cur = cur.parent()
            if not shadowed:
                to_delete.append(item)
        if len(to_delete) > 1:
            if QMessageBox.question(self, "Xóa nhiều mục",
                                    f"Xóa {len(to_delete)} mục đã chọn?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        for item in to_delete:
            obj = self._obj_of(item)
            cont = self._container_of(item)
            idx = self._index_by_identity(cont, obj) if cont is not None else -1
            if idx >= 0:
                cont.pop(idx)
        self._refresh_tree()

    def _move(self, delta):
        items = self._target_items()
        if not items:
            return
        moved = [self._obj_of(it) for it in items if self._obj_of(it) is not None]
        # Gom các object theo CONTAINER (mỗi container di chuyển độc lập, giữ thứ tự).
        groups: dict = {}     # id(container) -> (container, set(id(obj)))
        for it in items:
            obj = self._obj_of(it); cont = self._container_of(it)
            if cont is None or obj is None:
                continue
            g = groups.setdefault(id(cont), (cont, set()))
            g[1].add(id(obj))
        for cont, sel_ids in groups.values():
            idxs = [i for i, o in enumerate(cont) if id(o) in sel_ids]
            if delta < 0:                         # lên: duyệt từ trên xuống
                for i in idxs:
                    if i > 0 and id(cont[i - 1]) not in sel_ids:
                        cont[i - 1], cont[i] = cont[i], cont[i - 1]
            else:                                 # xuống: duyệt từ dưới lên
                for i in reversed(idxs):
                    if i < len(cont) - 1 and id(cont[i + 1]) not in sel_ids:
                        cont[i + 1], cont[i] = cont[i], cont[i + 1]
        self._refresh_tree()
        # Giữ highlight các dòng vừa di chuyển (kể cả nhiều dòng).
        self._loading = True
        for obj in moved:
            it = self._id_to_item.get(id(obj))
            if it is not None:
                it.setSelected(True)
        self._loading = False

    def _log(self, msg, color=Colors.TEXT_DIM):
        self.log.append(f"<font color='{color}'>{msg}</font>")

    # ------------------------------------------------------------------
    # Device manager / lưu / mở
    # ------------------------------------------------------------------
    def _open_command_reference(self):
        from gui.command_reference import CommandReferenceDialog
        dlg = CommandReferenceDialog(self)
        dlg.exec_()

    def _devices_for_flow(self):
        """Đổi ConnectionProfile -> danh sách thiết bị cho Flow Editor (None = demo)."""
        prof = getattr(self, "_profile", None)
        if not prof or not prof.entries:
            return None
        return [{"name": e.label or e.model_key, "key": e.model_key,
                 "sub": e.address or e.model_key, "icon": "🔌"} for e in prof.entries]

    def _switch_to_digital(self):
        """Chuyển sang theme Digital (node-flow), mang theo kịch bản hiện tại."""
        from gui.flow_editor import FlowEditorWindow
        # parent=None: cửa sổ top-level độc lập -> có icon taskbar riêng khi ẩn Classic.
        self._flow_win = FlowEditorWindow(devices=self._devices_for_flow(),
                                          parent=None, demo=False,
                                          on_export=self._apply_flow_scenario,
                                          on_switch=self._switch_from_digital,
                                          on_scan_device=self._scan_for_flow)
        self._flow_win.load_scenario(self.scenario)
        self._flow_win.show()
        self.hide()                       # ẩn Classic — chỉ hiện 1 theme tại 1 thời điểm

    def _scan_for_flow(self):
        """Callback cho FlowEditorWindow khi user click Step 1: mở dialog scan,
        trả về dict {"devices", "address_map", "cmd_delay_s"} hoặc None nếu hủy."""
        from gui.device_manager import DeviceManagerDialog
        from core.profile import ConnectionProfile
        prof = getattr(self, "_profile", ConnectionProfile())
        dlg = DeviceManagerDialog(self._flow_win, mock=False, profile=prof)
        if dlg.exec_() == QDialog.Accepted:
            self._profile = dlg.get_profile()
            self.address_map = self._profile.address_map()
            self._connected_keys = set(self.address_map.keys())
            self.cmd_delay_s = self._profile.cmd_delay_ms / 1000.0
            self._log(
                f"Đã cấu hình {len(self.address_map)} thiết bị: "
                f"{', '.join(self.address_map) or '(trống)'} "
                f"| delay: {self._profile.cmd_delay_ms}ms",
                Colors.ACCENT_GREEN)
            return {
                "devices": self._devices_for_flow() or [],
                "address_map": self.address_map,
                "cmd_delay_s": self.cmd_delay_s,
            }
        return None
        self._flow_win.show()
        self.hide()                       # ẩn Classic — chỉ hiện 1 theme tại 1 thời điểm

    def _switch_from_digital(self, scn):
        """Quay lại theme Classic từ Digital, mang theo kịch bản đã dựng."""
        if scn is not None:
            self.scenario = scn
            self._refresh_tree()
            self._log(f"Đã nhận {len(scn.nodes)} mục từ theme Digital.", Colors.ACCENT_GREEN)
        self.theme_toggle.setChecked(False, emit=False)   # về trạng thái Classic
        self.show()

    def _apply_flow_scenario(self, scn):
        """Nhận kịch bản từ Flow Editor (nút Xuất) -> thay kịch bản hiện tại."""
        self.scenario = scn
        self._refresh_tree()
        self._log(f"Đã nhập {len(scn.nodes)} mục từ theme Digital.", Colors.ACCENT_GREEN)

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
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item, QAbstractItemView.EnsureVisible)
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
