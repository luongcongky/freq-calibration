"""
gui/command_reference.py
========================
Màn hình tập lệnh (Command Reference) — danh sách lệnh SCPI theo dòng máy.

Mọi dòng máy đều có tập lệnh chung IEEE 488.2 (mặc định).
Khi chọn một dòng máy cụ thể, panel phải hiển thị thêm tập lệnh riêng.

Người dùng có thể:
  - Thêm lệnh mới vào bất kỳ dòng máy nào.
  - Sửa mô tả / ghi chú của lệnh đang có (cả chung lẫn riêng).
  - Xóa lệnh đã thêm hoặc ẩn lệnh tích hợp.
  - Khôi phục về mặc định cho dòng máy / lệnh chung.

Dữ liệu tuỳ chỉnh lưu tại: data/custom_commands.json
  Cấu trúc JSON:
    {
      "__common__": [{"cmd": ..., "desc": ..., "note": ...}, ...],
      "SMW200A":    [{"cmd": ..., "desc": ..., "note": ...}, ...]
    }
  Nếu một key có mặt trong file, toàn bộ danh sách tương ứng (chung hoặc riêng
  của device đó) được thay thế bởi nội dung từ file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget, QApplication,
    QLabel, QListWidget, QListWidgetItem, QComboBox, QFrame,
    QLineEdit, QAbstractItemView, QPushButton,
    QDialogButtonBox, QFormLayout, QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from drivers import DEVICE_REGISTRY
from gui.theme import Colors
from gui.widgets import paint_corner_brackets
from core.commands import (
    Cmd, COMMON_COMMANDS, DEVICE_COMMANDS,
    load_custom, CUSTOM_DATA_PATH, parse_cmd,
)

log = logging.getLogger(__name__)

# Role metadata cho ô đầu tiên mỗi dòng trong bảng
_ROLE_SRC = Qt.UserRole        # "common" | "device" | "custom" | None (header)
_ROLE_CMD = Qt.UserRole + 1   # Cmd object

_CAT_LABEL = {
    "generator": "Máy phát tín hiệu",
    "counter":   "Máy đếm tần số",
    "power":     "Máy đo công suất",
}
_CAT_ORDER = ["generator", "counter", "power"]

_MONO = QFont("Consolas", 9)
_MONO.setStyleHint(QFont.Monospace)

_MONO_LG = QFont("Consolas", 12, QFont.Bold)
_MONO_LG.setStyleHint(QFont.Monospace)


# ---------------------------------------------------------------------------
# Helper: load / save custom_commands.json
# ---------------------------------------------------------------------------

def _save_custom(data: dict[str, list[dict]]) -> None:
    CUSTOM_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CUSTOM_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("Không ghi được custom_commands.json: %s", e)


def _cmds_from_json(rows: list[dict]) -> list[Cmd]:
    return [Cmd(r.get("cmd", ""), r.get("desc", ""), r.get("note", "")) for r in rows]


def _cmds_to_json(cmds: list[Cmd]) -> list[dict]:
    return [asdict(c) for c in cmds]


# ---------------------------------------------------------------------------
# Dialog: soạn / chỉnh sửa một lệnh
# ---------------------------------------------------------------------------

class _CmdEditorDialog(QDialog):
    def __init__(self, parent=None, cmd: Cmd | None = None, title: str = "Soạn lệnh"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.cmd_edit = QLineEdit(cmd.cmd if cmd else "")
        self.cmd_edit.setFont(_MONO)
        self.cmd_edit.setPlaceholderText("Ví dụ: SENS1:FREQ 1E9")
        form.addRow("Lệnh:", self.cmd_edit)

        self.desc_edit = QLineEdit(cmd.desc if cmd else "")
        self.desc_edit.setPlaceholderText("Mô tả ngắn bằng tiếng Việt")
        form.addRow("Mô tả:", self.desc_edit)

        self.note_edit = QLineEdit(cmd.note if cmd else "")
        self.note_edit.setPlaceholderText("Ghi chú tùy chọn (dải tham số, ví dụ…)")
        form.addRow("Ghi chú:", self.note_edit)

        root.addLayout(form)

        hint = QLabel(
            "<font color='#a0a5ad'>Dùng <b>&lt;ch&gt;</b> cho số kênh, "
            "<b>&lt;Hz&gt;</b> / <b>&lt;s&gt;</b> / <b>&lt;dBm&gt;</b> cho tham số.</font>"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._result: Cmd | None = None

    def _on_ok(self):
        cmd_text = self.cmd_edit.text().strip()
        if not cmd_text:
            QMessageBox.warning(self, "Thiếu lệnh", "Vui lòng nhập cú pháp lệnh.")
            return
        desc_text = self.desc_edit.text().strip()
        if not desc_text:
            QMessageBox.warning(self, "Thiếu mô tả", "Vui lòng nhập mô tả cho lệnh.")
            return
        self._result = Cmd(cmd_text, desc_text, self.note_edit.text().strip())
        self.accept()

    def get_cmd(self) -> Cmd | None:
        return self._result


# ---------------------------------------------------------------------------
# Dialog chính: Tập lệnh thiết bị
# ---------------------------------------------------------------------------

class CommandReferenceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tập lệnh thiết bị — Command Reference")
        self.setMinimumSize(1150, 680)

        self._custom: dict[str, list[dict]] = load_custom()
        self._model_key: str = ""
        # Danh sách đang hiển thị, mỗi phần tử: (src, Cmd)
        # src = "common" | "device" | "custom"
        self._rows: list[tuple[str, Cmd]] = []
        self._param_widgets: dict[str, QWidget] = {}
        self._current_template: str = ""

        self._build_ui()
        self._populate_device_list()

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    # ------------------------------------------------------------------
    # Xây dựng UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)

        # --- Panel trái: chọn dòng máy + danh sách lệnh ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(6)
        ll.addWidget(QLabel("Chọn dòng máy:"))
        self.dev_list = QListWidget()
        self.dev_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.dev_list.setMaximumHeight(150)
        # Giữ NGUYÊN màu nền dòng máy đang chọn kể cả khi list mất focus (vd khi
        # bấm sang danh sách lệnh) — tránh cảm giác bị bỏ chọn.
        self.dev_list.setStyleSheet(
            f"QListWidget::item:selected {{ background:{Colors.ACCENT_PRIMARY};"
            f" color:{Colors.BG_WINDOW}; }}")
        self.dev_list.currentRowChanged.connect(self._on_device_changed)
        ll.addWidget(self.dev_list)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)

        def _btn(text, slot, tip=""):
            b = QPushButton(text)
            b.setFixedHeight(28)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            tool_row.addWidget(b)
            return b

        _btn("➕ Thêm", self._add_cmd, "Thêm lệnh mới vào dòng máy này")
        _btn("↩ Mặc định", self._reset_defaults, "Khôi phục lệnh gốc cho dòng máy này")
        ll.addLayout(tool_row)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm lệnh hoặc mô tả…")
        self.search_edit.textChanged.connect(self._apply_filter)
        ll.addWidget(self.search_edit)

        self.cmd_list = QListWidget()
        self.cmd_list.setSpacing(1)
        self.cmd_list.setStyleSheet(
            f"QListWidget::item:selected {{ background:rgba(255,204,68,40);"
            f" border-left:3px solid {Colors.ACCENT_PRIMARY}; }}")
        self.cmd_list.currentItemChanged.connect(self._on_selection_changed)
        self.cmd_list.itemDoubleClicked.connect(self._on_double_click)
        ll.addWidget(self.cmd_list, 1)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:9pt;")
        ll.addWidget(self.status_lbl)
        splitter.addWidget(left)

        # --- Panel phải: chi tiết lệnh đang chọn ---
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 0, 0, 0)
        rl.setSpacing(6)

        self.detail_name = QLabel("Chọn 1 lệnh bên trái để xem chi tiết")
        self.detail_name.setFont(_MONO_LG)
        self.detail_name.setStyleSheet(f"color:{Colors.ACCENT_PRIMARY};")
        rl.addWidget(self.detail_name)

        self.detail_desc = QLabel("")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setStyleSheet(f"color:{Colors.TEXT_MAIN}; font-size:11px;")
        rl.addWidget(self.detail_desc)

        self.tag_row = QHBoxLayout()
        self.tag_row.setSpacing(6)
        self.tag_row.addStretch()
        rl.addLayout(self.tag_row)

        params_hdr = QLabel("THAM SỐ")
        params_hdr.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px; font-weight:bold;")
        rl.addWidget(params_hdr)

        self.param_form = QFormLayout()
        rl.addLayout(self.param_form)
        self.no_param_lbl = QLabel("(lệnh không có tham số)")
        self.no_param_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        rl.addWidget(self.no_param_lbl)

        preview_hdr = QLabel("LỆNH SẼ GỬI")
        preview_hdr.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px; font-weight:bold;")
        rl.addWidget(preview_hdr)
        self.preview_lbl = QLabel("")
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setStyleSheet(
            f"background:{Colors.BG_DEEP}; border:1px solid {Colors.BORDER}; "
            f"color:{Colors.ACCENT_GREEN}; padding:8px 10px; font-family:Consolas;")
        rl.addWidget(self.preview_lbl)
        rl.addStretch()

        bottom_bar = QHBoxLayout()
        self.btn_edit = QPushButton("✏ Sửa lệnh")
        self.btn_edit.clicked.connect(self._edit_cmd)
        bottom_bar.addWidget(self.btn_edit)
        self.btn_del = QPushButton("🗑 Xóa lệnh")
        self.btn_del.clicked.connect(self._delete_cmd)
        bottom_bar.addWidget(self.btn_del)
        bottom_bar.addStretch()
        self.btn_copy = QPushButton("📋 Copy lệnh")
        self.btn_copy.setToolTip("Copy chuỗi lệnh (đã điền tham số) vào clipboard")
        self.btn_copy.clicked.connect(self._copy_command)
        bottom_bar.addWidget(self.btn_copy)
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        rl.addLayout(bottom_bar)

        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.btn_copy.setEnabled(False)

        splitter.addWidget(right)
        splitter.setSizes([340, 810])
        root.addWidget(splitter)
        self._show_detail(None)

    # ------------------------------------------------------------------
    # Danh sách thiết bị (trái)
    # ------------------------------------------------------------------
    def _populate_device_list(self):
        groups: dict[str, list[str]] = {c: [] for c in _CAT_ORDER}
        for key, entry in DEVICE_REGISTRY.items():
            cat = entry["category"]
            if cat in groups:
                groups[cat].append(key)

        first_row: int | None = None
        for cat in _CAT_ORDER:
            keys = groups.get(cat, [])
            if not keys:
                continue
            hdr = QListWidgetItem(f"  {_CAT_LABEL.get(cat, cat).upper()}")
            hdr.setFlags(Qt.NoItemFlags)
            hdr.setForeground(QColor(Colors.ACCENT_PRIMARY))
            f = hdr.font(); f.setBold(True); hdr.setFont(f)
            hdr.setBackground(QColor(Colors.BG_CARD))
            self.dev_list.addItem(hdr)
            for key in keys:
                entry = DEVICE_REGISTRY[key]
                item = QListWidgetItem(f"    {key}   —   {entry['vendor']}")
                item.setData(Qt.UserRole, key)
                self.dev_list.addItem(item)
                if first_row is None:
                    first_row = self.dev_list.count() - 1

        if first_row is not None:
            self.dev_list.setCurrentRow(first_row)

    # ------------------------------------------------------------------
    # Chọn thiết bị
    # ------------------------------------------------------------------
    def _on_device_changed(self, row: int):
        if row < 0:
            return
        item = self.dev_list.item(row)
        if item is None or not item.data(Qt.UserRole):
            return
        self._model_key = item.data(Qt.UserRole)
        self._rebuild_rows()
        self._rebuild_list()

    def _rebuild_rows(self):
        """Tạo lại self._rows từ built-in + custom_commands.json."""
        key = self._model_key
        custom = self._custom

        if "__common__" in custom:
            common_list = _cmds_from_json(custom["__common__"])
        else:
            common_list = list(COMMON_COMMANDS)

        if key in custom:
            device_list = _cmds_from_json(custom[key])
        else:
            device_list = list(DEVICE_COMMANDS.get(key, []))

        self._rows = (
            [("common", c) for c in common_list] +
            [("device", c) for c in device_list]
        )

    # ------------------------------------------------------------------
    # Danh sách lệnh (trái) + panel chi tiết (phải)
    # ------------------------------------------------------------------
    def _rebuild_list(self):
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.cmd_list.clear()
        self._show_detail(None)

        cls = DEVICE_REGISTRY.get(self._model_key, {}).get("cls")
        model_name = getattr(cls, "MODEL_NAME", self._model_key) if cls else self._model_key

        common_rows = [(s, c) for s, c in self._rows if s == "common"]
        device_rows = [(s, c) for s, c in self._rows if s != "common"]

        self._add_section_header("LỆNH CHUNG IEEE 488.2")
        for src, cmd in common_rows:
            self._add_cmd_item(src, cmd)

        self._add_section_header(f"LỆNH RIÊNG — {model_name}")
        if device_rows:
            for src, cmd in device_rows:
                self._add_cmd_item(src, cmd)
        else:
            self._add_empty_note("(Chưa có lệnh riêng — nhấn ➕ Thêm để bổ sung)")

        n_common = len(common_rows)
        n_device = len(device_rows)
        self.status_lbl.setText(
            f"{model_name}  —  {n_common} lệnh chung + {n_device} lệnh riêng"
            f"  =  {n_common + n_device} lệnh"
        )

    def _add_section_header(self, text: str):
        item = QListWidgetItem(f"── {text} ──")
        item.setFlags(Qt.NoItemFlags)
        f = item.font(); f.setBold(True); item.setFont(f)
        item.setForeground(QColor(Colors.ACCENT_PRIMARY))
        item.setBackground(QColor(Colors.BG_CARD))
        item.setData(_ROLE_SRC, None)
        self.cmd_list.addItem(item)

    def _add_cmd_item(self, src: str, cmd: Cmd):
        is_custom = src == "custom"
        is_override = src in ("common", "device") and self._is_overridden(src, cmd)
        if is_custom:
            color = Colors.ACCENT_WARN
        elif is_override:
            color = Colors.ACCENT_PRIMARY
        else:
            color = Colors.ACCENT_GREEN

        item = QListWidgetItem()
        item.setData(_ROLE_SRC, src)
        item.setData(_ROLE_CMD, cmd)
        self.cmd_list.addItem(item)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(1)
        name_lbl = QLabel(cmd.cmd)
        name_lbl.setFont(_MONO)
        name_lbl.setStyleSheet(f"color:{color};")
        lay.addWidget(name_lbl)
        desc_lbl = QLabel(cmd.desc)
        desc_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
        lay.addWidget(desc_lbl)
        item.setSizeHint(w.sizeHint())
        self.cmd_list.setItemWidget(item, w)

    def _add_empty_note(self, text: str):
        item = QListWidgetItem(text)
        item.setForeground(QColor(Colors.TEXT_DIM))
        item.setFlags(Qt.NoItemFlags)
        item.setData(_ROLE_SRC, None)
        self.cmd_list.addItem(item)

    def _is_overridden(self, src: str, cmd: Cmd) -> bool:
        if src == "common":
            return "__common__" in self._custom
        if src == "device":
            return self._model_key in self._custom
        return False

    # ------------------------------------------------------------------
    # Tìm kiếm
    # ------------------------------------------------------------------
    def _apply_filter(self, text: str):
        # Header/ghi chú trống (_ROLE_CMD is None) LUÔN hiện — chỉ lọc dòng lệnh
        # thật, giống hành vi bảng cũ (không ẩn tiêu đề nhóm dù rỗng kết quả).
        text_l = text.lower()
        for i in range(self.cmd_list.count()):
            item = self.cmd_list.item(i)
            cmd = item.data(_ROLE_CMD)
            if cmd is None:
                item.setHidden(False)
                continue
            match = not text_l or text_l in cmd.cmd.lower() or text_l in cmd.desc.lower()
            item.setHidden(not match)

    # ------------------------------------------------------------------
    # Selection + panel chi tiết
    # ------------------------------------------------------------------
    def _on_selection_changed(self, current, _prev=None):
        src = current.data(_ROLE_SRC) if current is not None else None
        cmd = current.data(_ROLE_CMD) if current is not None else None
        self.btn_edit.setEnabled(src is not None)
        self.btn_del.setEnabled(src is not None)
        self._show_detail(cmd, src)

    def _on_double_click(self, item):
        if item.data(_ROLE_SRC) is not None:
            self._edit_cmd()

    def _current_src(self) -> str | None:
        item = self.cmd_list.currentItem()
        return item.data(_ROLE_SRC) if item is not None else None

    def _current_cmd(self) -> Cmd | None:
        item = self.cmd_list.currentItem()
        return item.data(_ROLE_CMD) if item is not None else None

    def _show_detail(self, cmd: Cmd | None, src: str | None = None):
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self._param_widgets.clear()

        if cmd is None:
            self.detail_name.setText("Chọn 1 lệnh bên trái để xem chi tiết")
            self.detail_desc.setText("")
            self._clear_tags()
            self._current_template = ""
            self.no_param_lbl.setVisible(True)
            self.preview_lbl.setText("")
            self.btn_copy.setEnabled(False)
            return

        self.detail_name.setText(cmd.cmd)
        self.detail_desc.setText(cmd.desc + (f"  ({cmd.note})" if cmd.note else ""))

        template, params, is_query = parse_cmd(cmd)
        self._current_template = template
        cls = DEVICE_REGISTRY.get(self._model_key, {}).get("cls")
        model_name = getattr(cls, "MODEL_NAME", self._model_key) if cls else self._model_key
        device_tag = "Lệnh chung" if src == "common" else model_name
        self._set_tags(device_tag, "Query" if is_query else "Set")

        self.no_param_lbl.setVisible(not params)
        for p in params:
            if p.ptype == "enum":
                w = QComboBox()
                for c in p.choices:
                    w.addItem(c, c)
                w.currentIndexChanged.connect(self._update_preview)
            else:
                w = QLineEdit(str(p.default))
                w.textChanged.connect(self._update_preview)
            label = p.label + (f" ({p.unit})" if p.unit else "") + ":"
            self.param_form.addRow(label, w)
            self._param_widgets[p.name] = w

        self.btn_copy.setEnabled(True)
        self._update_preview()

    def _clear_tags(self):
        while self.tag_row.count() > 1:   # giữ lại addStretch() ở cuối
            item = self.tag_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _set_tags(self, device_text: str, type_text: str):
        self._clear_tags()
        dev_tag = QLabel(device_text)
        dev_tag.setStyleSheet(
            "color:#4488ff; border:1px solid #1a3a7a; background:#060e20;"
            " padding:2px 8px; font-size:10px; font-weight:bold;")
        type_tag = QLabel(type_text)
        type_tag.setStyleSheet(
            "color:#aa88ff; border:1px solid #4a2a7a; background:#0a0618;"
            " padding:2px 8px; font-size:10px; font-weight:bold;")
        self.tag_row.insertWidget(0, dev_tag)
        self.tag_row.insertWidget(1, type_tag)

    def _update_preview(self):
        if not self._current_template:
            self.preview_lbl.setText("")
            return
        sub = {}
        for name, w in self._param_widgets.items():
            if isinstance(w, QComboBox):
                sub[name] = w.currentData()
            else:
                sub[name] = w.text().strip() or "…"
        try:
            self.preview_lbl.setText(self._current_template.format(**sub))
        except (KeyError, ValueError):
            self.preview_lbl.setText(self._current_template)

    def _copy_command(self):
        text = self.preview_lbl.text()
        if text:
            QApplication.clipboard().setText(text)
            self.status_lbl.setText(f"Đã copy: {text}")

    # ------------------------------------------------------------------
    # Thêm lệnh
    # ------------------------------------------------------------------
    def _add_cmd(self):
        if not self._model_key:
            return
        dlg = _CmdEditorDialog(self, title="Thêm lệnh mới")
        if dlg.exec_() != QDialog.Accepted:
            return
        new_cmd = dlg.get_cmd()
        self._rows.append(("custom", new_cmd))
        self._persist_device_rows()
        self._rebuild_list()

    # ------------------------------------------------------------------
    # Sửa lệnh
    # ------------------------------------------------------------------
    def _edit_cmd(self):
        src = self._current_src()
        old_cmd = self._current_cmd()
        if src is None or old_cmd is None:
            return

        cls = DEVICE_REGISTRY.get(self._model_key, {}).get("cls")
        model_name = getattr(cls, "MODEL_NAME", self._model_key) if cls else self._model_key
        dlg = _CmdEditorDialog(self, cmd=old_cmd, title=f"Sửa lệnh  —  {model_name}")
        if dlg.exec_() != QDialog.Accepted:
            return
        new_cmd = dlg.get_cmd()

        for i, (s, c) in enumerate(self._rows):
            if c is old_cmd:
                self._rows[i] = (s, new_cmd)
                break

        if src == "common":
            self._persist_common_rows()
        else:
            self._persist_device_rows()

        self._rebuild_list()

    # ------------------------------------------------------------------
    # Xóa lệnh
    # ------------------------------------------------------------------
    def _delete_cmd(self):
        src = self._current_src()
        old_cmd = self._current_cmd()
        if src is None or old_cmd is None:
            return

        label = old_cmd.cmd[:60] + ("…" if len(old_cmd.cmd) > 60 else "")
        reply = QMessageBox.question(
            self, "Xác nhận xóa",
            f"Xóa lệnh:\n  {label}\n\nLệnh tích hợp sẽ biến mất khỏi dòng máy này "
            f"(dùng ↩ Mặc định để phục hồi).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._rows = [(s, c) for s, c in self._rows if c is not old_cmd]

        if src == "common":
            self._persist_common_rows()
        else:
            self._persist_device_rows()

        self._rebuild_list()

    # ------------------------------------------------------------------
    # Khôi phục mặc định
    # ------------------------------------------------------------------
    def _reset_defaults(self):
        if not self._model_key:
            return
        cls = DEVICE_REGISTRY.get(self._model_key, {}).get("cls")
        model_name = getattr(cls, "MODEL_NAME", self._model_key) if cls else self._model_key

        reply = QMessageBox.question(
            self, "Khôi phục mặc định",
            f"Khôi phục tập lệnh gốc cho:\n  {model_name}\n\n"
            "Mọi thay đổi (thêm / sửa / xóa) sẽ bị mất.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._custom.pop(self._model_key, None)
        _save_custom(self._custom)
        self._rebuild_rows()
        self._rebuild_list()

    # ------------------------------------------------------------------
    # Lưu JSON
    # ------------------------------------------------------------------
    def _persist_common_rows(self):
        common_cmds = [c for s, c in self._rows if s == "common"]
        self._custom["__common__"] = _cmds_to_json(common_cmds)
        _save_custom(self._custom)

    def _persist_device_rows(self):
        device_cmds = [c for s, c in self._rows if s != "common"]
        self._custom[self._model_key] = _cmds_to_json(device_cmds)
        _save_custom(self._custom)
