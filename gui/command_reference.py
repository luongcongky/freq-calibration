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
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QLabel, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QAbstractItemView, QPushButton,
    QDialogButtonBox, QFormLayout, QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from drivers import DEVICE_REGISTRY
from gui.theme import Colors
from core.commands import (
    Cmd, COMMON_COMMANDS, DEVICE_COMMANDS,
    load_custom, CUSTOM_DATA_PATH,
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
        self.setMinimumSize(1020, 640)

        self._custom: dict[str, list[dict]] = load_custom()
        self._model_key: str = ""
        # Danh sách đang hiển thị, mỗi phần tử: (src, Cmd)
        # src = "common" | "device" | "custom"
        self._rows: list[tuple[str, Cmd]] = []

        self._build_ui()
        self._populate_device_list()

    # ------------------------------------------------------------------
    # Xây dựng UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)

        # --- Panel trái ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(6)
        ll.addWidget(QLabel("Chọn dòng máy:"))
        self.dev_list = QListWidget()
        self.dev_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.dev_list.currentRowChanged.connect(self._on_device_changed)
        ll.addWidget(self.dev_list)
        splitter.addWidget(left)

        # --- Panel phải ---
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.setSpacing(6)

        # Thanh tìm kiếm + nút hành động
        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)

        lbl = QLabel("Tìm:")
        lbl.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Nhập lệnh hoặc mô tả…")
        self.search_edit.textChanged.connect(self._apply_filter)
        tool_row.addWidget(lbl)
        tool_row.addWidget(self.search_edit, 1)

        tool_row.addSpacing(12)

        def _btn(text, slot, tip=""):
            b = QPushButton(text)
            b.setFixedHeight(30)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            tool_row.addWidget(b)
            return b

        _btn("➕ Thêm",   self._add_cmd,      "Thêm lệnh mới vào dòng máy này")
        self.btn_edit = _btn("✏ Sửa",    self._edit_cmd,     "Sửa lệnh đang chọn (hoặc nhấp đúp)")
        self.btn_del  = _btn("🗑 Xóa",    self._delete_cmd,   "Xóa lệnh đang chọn")
        _btn("↩ Mặc định", self._reset_defaults, "Khôi phục lệnh gốc cho dòng máy này")

        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)

        rl.addLayout(tool_row)

        # Bảng lệnh
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Lệnh", "Mô tả", "Ghi chú"])
        # Interactive = kéo rộng/hẹp tự do. Cột cuối tự dãn lấp chỗ trống.
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(60)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(1, 360)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        rl.addWidget(self.table)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:9pt;")
        rl.addWidget(self.status_lbl)

        splitter.addWidget(right)
        splitter.setSizes([230, 790])
        root.addWidget(splitter)

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
            hdr.setForeground(QColor(Colors.ACCENT_CYAN))
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
        self._rebuild_table()

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
    # Bảng lệnh (phải)
    # ------------------------------------------------------------------
    def _rebuild_table(self):
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.table.setRowCount(0)
        self.btn_edit.setEnabled(False)
        self.btn_del.setEnabled(False)

        cls = DEVICE_REGISTRY.get(self._model_key, {}).get("cls")
        model_name = getattr(cls, "MODEL_NAME", self._model_key) if cls else self._model_key

        common_rows = [(s, c) for s, c in self._rows if s == "common"]
        device_rows = [(s, c) for s, c in self._rows if s != "common"]

        self._add_section("Lệnh chung IEEE 488.2  —  áp dụng cho mọi dòng máy")
        for src, cmd in common_rows:
            self._add_cmd_row(src, cmd)

        self._add_section(f"Lệnh riêng  —  {model_name}")
        if device_rows:
            for src, cmd in device_rows:
                self._add_cmd_row(src, cmd)
        else:
            self._add_empty_note("(Chưa có lệnh riêng — nhấn ➕ Thêm để bổ sung)")

        n_common = len(common_rows)
        n_device = len(device_rows)
        self.status_lbl.setText(
            f"{model_name}  —  {n_common} lệnh chung + {n_device} lệnh riêng"
            f"  =  {n_common + n_device} lệnh"
        )

    def _add_section(self, text: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(f"  {text}")
        item.setBackground(QColor(Colors.BG_CARD))
        item.setForeground(QColor(Colors.ACCENT_CYAN))
        f = item.font(); f.setBold(True); item.setFont(f)
        item.setFlags(Qt.NoItemFlags)
        item.setData(_ROLE_SRC, None)
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, 3)
        self.table.setRowHeight(row, 30)

    def _add_cmd_row(self, src: str, cmd: Cmd):
        row = self.table.rowCount()
        self.table.insertRow(row)

        is_custom = src == "custom"
        is_override = src in ("common", "device") and self._is_overridden(src, cmd)

        col0 = QTableWidgetItem(f"  {cmd.cmd}")
        col0.setFont(_MONO)
        if is_custom:
            col0.setForeground(QColor(Colors.ACCENT_WARN))
        elif is_override:
            col0.setForeground(QColor(Colors.ACCENT_CYAN))
        else:
            col0.setForeground(QColor(Colors.ACCENT_GREEN))
        col0.setData(_ROLE_SRC, src)
        col0.setData(_ROLE_CMD, cmd)

        col1 = QTableWidgetItem(cmd.desc)
        col1.setForeground(QColor(Colors.TEXT_MAIN))
        if is_custom or is_override:
            f2 = col1.font(); f2.setItalic(True); col1.setFont(f2)

        col2 = QTableWidgetItem(cmd.note)
        col2.setForeground(QColor(Colors.TEXT_DIM))
        col2.setFont(QFont("Segoe UI", 8))

        self.table.setItem(row, 0, col0)
        self.table.setItem(row, 1, col1)
        self.table.setItem(row, 2, col2)
        self.table.setRowHeight(row, 26)

    def _add_empty_note(self, text: str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(f"  {text}")
        item.setForeground(QColor(Colors.TEXT_DIM))
        item.setFlags(Qt.NoItemFlags)
        item.setData(_ROLE_SRC, None)
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, 3)

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
        text_l = text.lower()
        for row in range(self.table.rowCount()):
            if self.table.columnSpan(row, 0) > 1:
                self.table.setRowHidden(row, False)
                continue
            c0 = self.table.item(row, 0)
            c1 = self.table.item(row, 1)
            c2 = self.table.item(row, 2)
            match = (
                (c0 and text_l in c0.text().lower()) or
                (c1 and text_l in c1.text().lower()) or
                (c2 and text_l in c2.text().lower())
            )
            self.table.setRowHidden(row, not match if text_l else False)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _on_selection_changed(self):
        row = self.table.currentRow()
        src = self._row_src(row)
        self.btn_edit.setEnabled(src is not None)
        self.btn_del.setEnabled(src is not None)

    def _on_double_click(self, item):
        if self._row_src(item.row()) is not None:
            self._edit_cmd()

    def _row_src(self, row: int) -> str | None:
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(_ROLE_SRC)

    def _row_cmd(self, row: int) -> Cmd | None:
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(_ROLE_CMD)

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
        self._rebuild_table()

    # ------------------------------------------------------------------
    # Sửa lệnh
    # ------------------------------------------------------------------
    def _edit_cmd(self):
        row = self.table.currentRow()
        src = self._row_src(row)
        old_cmd = self._row_cmd(row)
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

        self._rebuild_table()

    # ------------------------------------------------------------------
    # Xóa lệnh
    # ------------------------------------------------------------------
    def _delete_cmd(self):
        row = self.table.currentRow()
        src = self._row_src(row)
        old_cmd = self._row_cmd(row)
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

        self._rebuild_table()

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
        self._rebuild_table()

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
