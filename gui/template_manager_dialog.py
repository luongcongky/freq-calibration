"""
gui/template_manager_dialog.py
================================
"Quản lý mẫu báo cáo" — THAY HẲN gui/template_scan_dialog.py cũ. Không còn
đường "tạo mẫu rỗng": 2 lối vào duy nhất, cả 2 đều bắt đầu từ 1 mẫu THẬT
đã có (xem thiết kế đã chốt với khách hàng):

  - ✏️ Sửa mẫu đã có (tại chỗ — có dải cảnh báo, lối tắt sang Sao chép)
  - 📋 Sao chép mẫu đã có -> mẫu mới -> mở luôn để sửa (an toàn hơn)

Cấu trúc màn hình (khớp mockup HUD navy/gold):
  TemplateManagerDialog — MỘT màn hình: danh sách mẫu (trái) + editor 3 tab
                           Thông tin chung / Bảng dữ liệu / File Word (phải) —
                           chọn mẫu ở list trái là editor phải nạp lại ngay,
                           không còn mở dialog sửa riêng như trước.
  CopyTemplateDialog    — modal nhỏ: chỉ hỏi mã mới + tên hiển thị
  TableFormDialog       — form 1 bảng "đơn giản" (thêm mới HOẶC sửa lại) —
                           tái dùng logic wizard cũ, bỏ hẳn phần GCN kiểu
                           "summary_rows" (không còn template nào dùng).

Toàn bộ logic ghi thật nằm ở core/table_import.py + core/table_wizard_io.py
— file này chỉ thu thập input rồi gọi thẳng vào đó.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QSpinBox, QRadioButton, QButtonGroup, QGroupBox,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QWidget,
    QTabWidget, QScrollArea, QSizePolicy, QTextEdit, QDialogButtonBox, QFrame,
    QListWidget, QListWidgetItem, QSplitter,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from gui.theme import Colors
from gui.file_dialog_utils import get_open_file_name
from gui.widgets import paint_corner_brackets
from core import table_wizard_io as wio
from core import table_import as timport
from core.report_templates import list_templates
from core.report_templates.generic import TEMPLATES_DIR, template_summary
from core.table_descriptor import RowDef, load_table_descriptors, validate_descriptor
from dataclasses import replace as _dc_replace

SYNTAX_CHEAT_SHEET = """\
FIELD TĨNH (1 lần/tài liệu) — lấy từ "Thông tin phiên":
  {{ header.name }}             Tên phương tiện ĐL-TN
  {{ header.no }}                Ký hiệu/model
  {{ header.serial }}            Số serial
  {{ header.country }}           Hãng sản xuất
  {{ header.birthday }}          Năm sản xuất
  {{ header.company }}           Đơn vị sử dụng
  {{ header.Characteristics }}   Đặc tính đo lường / dải đo
  {{ header.conclusion }}        Kết luận (Đạt/Không đạt — mọi kind)
  {{ header.expire }}            Ngày hết hạn hiệu lực (chỉ kiểm định)
  {{ header.reviewer }}          Người soát lại
  {{ header.inspector }}         Kiểm định viên
  {{ header.manager }}           Thủ trưởng đơn vị (ký GCN)
  {{ header.temperature }}       Nhiệt độ môi trường
  {{ header.humidity }}          Độ ẩm môi trường
  {{ header.equipment }}         Phương tiện hiệu chuẩn/kiểm định dùng
  {{ header.cert_no }}           Số giấy chứng nhận
  {{ header.today }}             Ngày lập biên bản
  {{ header.cal_date }}          Ngày hiệu chuẩn (GCN hiệu chuẩn)
  {{ header.sign_date }}         Ngày ký GCN

ẨN/HIỆN CẢ MỤC theo bài test có bật hay không — bọc quanh tiêu đề + bảng:
  {% if tables.<Mã bảng>.enabled %}
  ... tiêu đề + bảng ...
  {% endif %}

GIÁ TRỊ ĐO TUẦN TỰ trong bảng (BIÊN BẢN) — đặt trực tiếp vào từng ô, ĐÚNG
THỨ TỰ trái→phải, trên→dưới (gọi bao nhiêu lần thì lấy đúng bấy nhiêu dòng
kế tiếp trong "Dữ liệu từng dòng" — số lần gọi PHẢI KHỚP đúng số dòng, gọi
dư sẽ báo cảnh báo "đẩy dư report_val" ở Bước 2):
  {{ tables.<Mã bảng>.report_val() }}     ĐÚNG giá trị đo kịch bản đã đẩy —
                                           Biên Bản CHỈ đọc từ report_val(),
                                           không có công thức tự suy diễn.

TỔNG KẾT 1 DÒNG/BÀI TEST trong Giấy chứng nhận (GCN) — chọn 1 trong 2 kiểu:
  (a) {%tr if tables.<Mã bảng>.enabled %}
      {{ tables.<Mã bảng>.result }}
      {%tr endif %}
      "Đạt/Không đạt" — chỉ có ý nghĩa khi quy tắc Đạt/Không đạt của bảng
      có tính passed (relative_error_vs_fixed_limit/value_vs_parsed_threshold).

      Ví dụ THẬT — mẫu TEMPLATE_FREQ, bảng A1 (pass_rule
      relative_error_vs_fixed_limit), đúng nội dung đang có trong
      gcnkd.docx của mẫu này:
        {%tr if tables.A1.enabled %}
        1.Xác định sai số bộ dao động thạch anh | {{ tables.A1.result }} | ± 2,4×10⁻⁷
        {%tr endif %}

  (b) {{ tables.<Mã bảng>.gcn_avg() }}     trung bình các lần đo của dòng
      {{ tables.<Mã bảng>.gcn_error() }}   số hiệu chỉnh (chuẩn − trung bình)
      {{ tables.<Mã bảng>.gcn_limit() }}   ngưỡng của dòng (nếu có khai báo)
      Dùng cho văn bản HIỆU CHUẨN (pass_rule correction_vs_reference) —
      phần mềm tự tổng hợp lại từ ĐÚNG report_val() Biên Bản đã đẩy.

      Ví dụ minh hoạ — mẫu TEMPLATE_POWER, bảng A1 (pass_rule
      correction_vs_reference, value_format "w", dòng "1 mW" có
      uncertainty_index nên gcn_limit() ở đây trả về ĐÚNG giá trị Độ KĐBĐ
      kịch bản đã đẩy, không phải ngưỡng tĩnh):
        {{ tables.A1.gcn_avg() }}     -> TB 10 report_val() đo thật, format "w" (vd "0,001021 W")
        {{ tables.A1.gcn_error() }}   -> tự format correction_mw (auto suy từ value_format="w")
        {{ tables.A1.gcn_limit() }}   -> Độ KĐBĐ = report_val() thứ 12/12 kịch bản tự tính
"""

_KIND_LABELS = [("kiem_dinh", "Kiểm định"), ("hieu_chuan", "Hiệu chuẩn")]


def _fit_table_height(tbl: QTableWidget) -> None:
    """QTableWidget mặc định sizePolicy Expanding theo chiều dọc — khi nằm
    trong QVBoxLayout bên trong QScrollArea(resizable=True) cùng nhiều bảng
    khác, layout sẽ CO các bảng lại gần như chỉ còn header. Ép sizePolicy
    Fixed + tính đúng chiều cao theo số dòng thật để mọi dòng luôn hiện đủ."""
    tbl.resizeRowsToContents()
    height = tbl.horizontalHeader().height() + 2 * tbl.frameWidth() + 4
    for r in range(tbl.rowCount()):
        height += tbl.rowHeight(r)
    tbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    tbl.setFixedHeight(height)


def _combo(items, current=None) -> QComboBox:
    cb = QComboBox()
    for value, label in items:
        cb.addItem(label, value)
    if current is not None:
        idx = cb.findData(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
    return cb


def _show_syntax_help(parent):
    dlg = QDialog(parent)
    dlg.setWindowTitle("Hướng dẫn cú pháp tag Jinja")
    dlg.resize(720, 560)
    lay = QVBoxLayout(dlg)
    text = QTextEdit()
    text.setReadOnly(True)
    text.setFont(QFont("Consolas", 10))
    text.setPlainText(SYNTAX_CHEAT_SHEET)
    lay.addWidget(text)
    btns = QDialogButtonBox(QDialogButtonBox.Close)
    btns.rejected.connect(dlg.reject)
    btns.accepted.connect(dlg.accept)
    btns.button(QDialogButtonBox.Close).clicked.connect(dlg.accept)
    lay.addWidget(btns)
    dlg.exec_()


def _open_path(path) -> None:
    try:
        os.startfile(str(path))  # noqa: S606 — mở bằng ứng dụng mặc định
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(None, "Không mở được file", str(exc))


# =============================================================================
# 1) Danh sách mẫu — điểm vào
# =============================================================================

class TemplateManagerDialog(QDialog):
    """Danh sách mẫu (trái) + editor 3 tab (phải) trong CÙNG 1 màn hình —
    sửa "tại chỗ" đúng nghĩa (trước đây danh sách mở 1 dialog sửa riêng)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý mẫu báo cáo")
        self.setMinimumSize(1200, 700)
        self.changed = False   # True nếu có bất kỳ thay đổi nào cần refresh combobox chọn mẫu
        self.template_id: str | None = None
        self._just_copied_id: str | None = None

        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        # --- Trái: danh sách mẫu ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.addWidget(QLabel("Chọn 1 mẫu để sửa hoặc sao chép:"))
        self.tpl_list = QListWidget()
        self.tpl_list.setStyleSheet(
            f"QListWidget::item {{ border-left:3px solid transparent; }}"
            f"QListWidget::item:selected {{ border-left:3px solid {Colors.ACCENT_PRIMARY};"
            f" background:rgba(255,204,68,15); }}")
        self.tpl_list.currentItemChanged.connect(self._on_select_template)
        ll.addWidget(self.tpl_list, 1)

        list_bar = QHBoxLayout()
        self.btn_copy = QPushButton("📋 Sao chép…")
        self.btn_copy.clicked.connect(self._open_copy)
        list_bar.addWidget(self.btn_copy)
        self.btn_delete = QPushButton("🗑 Xoá")
        self.btn_delete.setStyleSheet(f"color:{Colors.ACCENT_RED};")
        self.btn_delete.clicked.connect(self._delete_current)
        list_bar.addWidget(self.btn_delete)
        ll.addLayout(list_bar)
        splitter.addWidget(left)

        # --- Phải: editor 3 tab ---
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 0, 0, 0)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setStyleSheet(f"color:{Colors.ACCENT_WARN}; font-size:11px;")
        self.lbl_warn.setWordWrap(True)
        rl.addWidget(self.lbl_warn)
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Thông tin chung")
        self.tabs.addTab(QWidget(), "Bảng dữ liệu")
        self.tabs.addTab(QWidget(), "File Word")
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)

        splitter.setSizes([300, 900])
        root.addWidget(splitter, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        nav.addWidget(btn_close)
        root.addLayout(nav)

        self._reload_list()

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    # ------------------------------------------------------------------
    # Danh sách mẫu (trái)
    # ------------------------------------------------------------------
    def _reload_list(self, select_id: str | None = None):
        self.tpl_list.clear()
        for tid, _ in list_templates():
            info = template_summary(tid)
            if info is None:
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, tid)
            self.tpl_list.addItem(item)
            w = self._build_list_item_widget(info)
            item.setSizeHint(w.sizeHint())
            self.tpl_list.setItemWidget(item, w)

        target = select_id or self.template_id
        idx = 0
        if target:
            for i in range(self.tpl_list.count()):
                if self.tpl_list.item(i).data(Qt.UserRole) == target:
                    idx = i
                    break
        if self.tpl_list.count():
            self.tpl_list.setCurrentRow(idx)
        else:
            self._load_template(None)

    def _build_list_item_widget(self, info: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(1)
        lbl_name = QLabel(info["template_name"])
        lbl_name.setStyleSheet("font-weight:bold;")
        lay.addWidget(lbl_name)
        lbl_id = QLabel(info["template_id"])
        lbl_id.setStyleSheet(f"color:{Colors.ACCENT_PRIMARY}; font-size:10px;")
        lay.addWidget(lbl_id)
        kind_txt = "Kiểm định" if info["kind"] == "kiem_dinh" else "Hiệu chuẩn"
        lbl_meta = QLabel(f"{kind_txt} · {info['n_tables']} bảng kết quả")
        lbl_meta.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
        lay.addWidget(lbl_meta)
        return w

    def _on_select_template(self, current, _prev):
        self._load_template(current.data(Qt.UserRole) if current is not None else None)

    def _open_copy(self):
        item = self.tpl_list.currentItem()
        if item is None:
            return
        tid = item.data(Qt.UserRole)
        info = template_summary(tid)
        dlg = CopyTemplateDialog(tid, info["template_name"] if info else tid, parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.new_template_id:
            self.changed = True
            self._just_copied_id = dlg.new_template_id
            self._reload_list(select_id=dlg.new_template_id)

    def _delete_current(self):
        item = self.tpl_list.currentItem()
        if item is None:
            return
        tid = item.data(Qt.UserRole)
        info = template_summary(tid)
        name = info["template_name"] if info else tid
        msg = (f"Xoá mẫu '{tid} — {name}'?\n\n"
               f"File sẽ chuyển vào Thùng rác Windows (khôi phục được nếu lỡ tay), "
               f"nhưng phiên kiểm định ĐÃ LƯU nào còn tham chiếu mẫu này sẽ không mở lại được nữa.")
        if QMessageBox.question(self, "Xác nhận xoá mẫu", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            timport.delete_template(tid)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi xoá", str(exc))
            return
        self.changed = True
        self.template_id = None
        self._reload_list()

    # ------------------------------------------------------------------
    # Editor (phải) — 3 tab: Thông tin chung / Bảng dữ liệu / File Word
    # ------------------------------------------------------------------
    @property
    def tpl_dir(self) -> Path:
        return TEMPLATES_DIR / self.template_id

    @property
    def tables_dir(self) -> Path:
        return self.tpl_dir / "tables"

    def _load_template(self, template_id: str | None):
        self.template_id = template_id
        if template_id is None:
            self.btn_copy.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self.lbl_warn.setText("")
            return
        self.btn_copy.setEnabled(True)
        self.btn_delete.setEnabled(True)
        self._meta = json.loads((self.tpl_dir / "meta.json").read_text(encoding="utf-8"))
        self._descriptors = load_table_descriptors(self.tables_dir)
        self._swap_tab(0, self._build_meta_tab(), "Thông tin chung")
        self._swap_tab(1, self._build_tables_tab(), f"Bảng dữ liệu ({len(self._descriptors)})")
        self._swap_tab(2, self._build_docx_tab(), "File Word")
        just_copied = template_id == self._just_copied_id
        self.lbl_warn.setText(
            "" if just_copied else
            "⚠ Đang sửa TRỰC TIẾP mẫu gốc — thay đổi áp dụng cho mọi phiên dùng mẫu này kể từ khi lưu.")

    def _swap_tab(self, index: int, new_widget: QWidget, label: str):
        """Thay TOÀN BỘ widget của 1 tab bằng widget mới dựng sẵn — AN TOÀN
        hơn nhiều so với "cướp" layout cũ rồi dựng lại layout mới trên cùng
        1 widget (kiểu QWidget().setLayout(old) từng gây crash: QWidget tạm
        không giữ tham chiếu Python bị GC trong khi Qt vẫn còn thao tác trên
        nó). Widget cũ được deleteLater() đúng cách qua Qt event loop."""
        old_widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, new_widget, label)
        if old_widget is not None:
            old_widget.deleteLater()

    def _mark_changed(self):
        self.changed = True

    # -- Tab 1: Thông tin chung ------------------------------------------

    def _build_meta_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.e_meta_name = QLineEdit(self._meta.get("template_name", ""))
        form.addRow("Tên hiển thị:", self.e_meta_name)

        self.e_meta_models = QLineEdit(", ".join(self._meta.get("dut_models", [])))
        self.e_meta_models.setPlaceholderText("vd MODEL1, MODEL2")
        form.addRow("Model DUT (phân cách bằng dấu phẩy):", self.e_meta_models)

        self.e_meta_mfr = QLineEdit(self._meta.get("dut_manufacturer_default", ""))
        form.addRow("Hãng sản xuất mặc định:", self.e_meta_mfr)

        self.e_meta_standard = QLineEdit(self._meta.get("standard", ""))
        form.addRow("Tiêu chuẩn:", self.e_meta_standard)

        self.e_meta_range = QLineEdit(self._meta.get("measurement_range", ""))
        form.addRow("Dải đo:", self.e_meta_range)

        kind_row = QHBoxLayout()
        self._kind_group = QButtonGroup(tab)
        current_kind = self._meta.get("kind", "kiem_dinh")
        for value, label in _KIND_LABELS:
            rb = QRadioButton(label)
            rb.setProperty("kind_value", value)
            rb.setChecked(value == current_kind)
            self._kind_group.addButton(rb)
            kind_row.addWidget(rb)
        kind_row.addStretch()
        form.addRow("Loại mẫu:", kind_row)

        btn_save = QPushButton("💾 Lưu thông tin chung")
        btn_save.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        btn_save.clicked.connect(self._save_meta)
        form.addRow(btn_save)
        return tab

    def _save_meta(self):
        kind_btn = self._kind_group.checkedButton()
        meta_fields = {
            "template_name": self.e_meta_name.text().strip() or self.template_id,
            "dut_models": [m.strip() for m in self.e_meta_models.text().split(",") if m.strip()],
            "dut_manufacturer_default": self.e_meta_mfr.text().strip(),
            "standard": self.e_meta_standard.text().strip(),
            "measurement_range": self.e_meta_range.text().strip(),
            "kind": kind_btn.property("kind_value") if kind_btn else "kiem_dinh",
        }
        try:
            timport.update_meta(self.template_id, meta_fields)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi lưu", str(exc))
            return
        self._mark_changed()
        self._load_template(self.template_id)
        self._reload_list()
        QMessageBox.information(self, "Đã lưu", "Đã lưu thông tin chung của mẫu.")

    # -- Tab 2: Bảng dữ liệu ------------------------------------------------

    def _build_tables_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        tbl = QTableWidget(len(self._descriptors), 6)
        tbl.setHorizontalHeaderLabels(["Mã", "Tên bài test", "Độ phức tạp", "", "", ""])
        tbl.horizontalHeader().setStretchLastSection(False)
        tbl.horizontalHeader().setSectionResizeMode(1, tbl.horizontalHeader().Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)

        for i, d in enumerate(self._descriptors):
            tbl.setItem(i, 0, QTableWidgetItem(d.table_id))
            tbl.setItem(i, 1, QTableWidgetItem(d.name))
            advanced = wio.is_advanced_table(d)
            tbl.setItem(i, 2, QTableWidgetItem("⚙ Nâng cao" if advanced else "✓ Đơn giản"))

            btn_detail = QPushButton("👁 Chi tiết")
            btn_detail.clicked.connect(lambda _c=False, tid=d.table_id: self._show_detail(tid))
            tbl.setCellWidget(i, 3, btn_detail)

            btn = QPushButton("Xem JSON" if advanced else "✏️ Sửa")
            if advanced:
                btn.clicked.connect(lambda _c=False, tid=d.table_id: _open_path(self.tables_dir / f"{tid}.json"))
            else:
                btn.clicked.connect(lambda _c=False, tid=d.table_id: self._edit_table(tid))
            tbl.setCellWidget(i, 4, btn)

            btn_copy = QPushButton("📋")
            btn_copy.setToolTip("Sao chép bảng này thành bảng mới")
            btn_copy.setFixedWidth(36)
            btn_copy.clicked.connect(lambda _c=False, tid=d.table_id, name=d.name: self._copy_table(tid, name))
            tbl.setCellWidget(i, 5, btn_copy)

        _fit_table_height(tbl)
        lay.addWidget(tbl)

        hint = QLabel("⚙ Nâng cao = bảng có field kịch bản tự tính thêm (sai số, TB, Độ KĐBĐ) — "
                       "form hiện chưa biểu diễn được, mở bằng ứng dụng mặc định để sửa file JSON.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        lay.addWidget(hint)

        lay.addStretch()
        return tab

    def _edit_table(self, table_id: str):
        existing = next((d for d in self._descriptors if d.table_id == table_id), None)
        if existing is None:
            return
        dlg = TableFormDialog(self.tables_dir, existing, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._mark_changed()
            self._load_template(self.template_id)

    def _show_detail(self, table_id: str):
        d = next((d for d in self._descriptors if d.table_id == table_id), None)
        if d is None:
            return
        dlg = TableDetailDialog(d, self.tables_dir, parent=self)
        dlg.exec_()
        if dlg.changed:
            self._mark_changed()
            self._load_template(self.template_id)

    def _copy_table(self, table_id: str, table_name: str):
        dlg = CopyTableDialog(self.tables_dir, table_id, table_name, parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.new_table_id:
            self._mark_changed()
            self._load_template(self.template_id)

    # -- Tab 3: File Word ----------------------------------------------------

    def _build_docx_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        for which, label in (("bienban", "Biên Bản (Phụ lục A)"), ("gcnkd", "Giấy Chứng Nhận (Phụ lục B)")):
            path = self.tpl_dir / f"{which}.docx"
            row = QFrame()
            row.setFrameShape(QFrame.StyledPanel)
            row_lay = QHBoxLayout(row)
            left = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight:bold;")
            left.addWidget(lbl)
            lbl_path = QLabel(str(path) if path.exists() else "(chưa có file)")
            lbl_path.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
            left.addWidget(lbl_path)
            row_lay.addLayout(left, 1)

            btn_view = QPushButton("👁 Mở xem")
            btn_view.setEnabled(path.exists())
            btn_view.clicked.connect(lambda _c=False, p=path: _open_path(p))
            row_lay.addWidget(btn_view)

            btn_replace = QPushButton("📂 Thay file…")
            btn_replace.clicked.connect(lambda _c=False, w=which: self._replace_docx(w))
            row_lay.addWidget(btn_replace)

            lay.addWidget(row)

        hint = QLabel("\"Thay file\" kiểm tra lại đủ tag tables.<mã bảng> cho từng bảng đang có trong file mới "
                       "— cảnh báo nếu thiếu, không tự sinh tag.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        lay.addWidget(hint)

        btn_help = QPushButton("📖 Xem hướng dẫn cú pháp tag")
        btn_help.clicked.connect(lambda: _show_syntax_help(self))
        lay.addWidget(btn_help)
        lay.addStretch()
        return tab

    def _replace_docx(self, which: str):
        path, _ = get_open_file_name(self, "Chọn file Word đã gắn tag sẵn", "", "Word Document (*.docx)")
        if not path:
            return
        ids = [d.table_id for d in self._descriptors]
        missing = wio.find_missing_table_ids(path, ids)
        if missing:
            msg = (f"Không thấy 'tables.<ID>' của {missing} trong file vừa chọn.\n\n"
                   f"Có thể do gõ nhầm mã bảng hoặc chưa gắn tag. Vẫn dùng file này?")
            if QMessageBox.question(self, "Cảnh báo", msg) != QMessageBox.Yes:
                return
        try:
            timport.replace_docx(self.template_id, which, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi thay file", str(exc))
            return
        self._mark_changed()
        self._load_template(self.template_id)
        QMessageBox.information(self, "Đã thay file", "Đã thay file thành công.")


# =============================================================================
# 2) Sao chép mẫu
# =============================================================================

class CopyTemplateDialog(QDialog):
    def __init__(self, source_id: str, source_name: str, parent=None):
        super().__init__(parent)
        self.source_id = source_id
        self.new_template_id = None

        self.setWindowTitle("Sao chép mẫu báo cáo")
        self.setMinimumWidth(480)
        form = QFormLayout(self)

        lbl_source = QLabel(f"{source_id} — {source_name}")
        lbl_source.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        form.addRow("Mẫu nguồn:", lbl_source)

        self.e_new_id = QLineEdit()
        self.e_new_id.setPlaceholderText(f"vd {source_id}_V2")
        form.addRow("Mã mẫu mới:", self.e_new_id)

        self.e_new_name = QLineEdit(f"{source_name} (bản sao)")
        form.addRow("Tên hiển thị:", self.e_new_name)

        hint = QLabel("Sao chép nguyên vẹn toàn bộ bảng dữ liệu + 2 file Word đã gắn tag — "
                       "sửa gì trên bản sao cũng không ảnh hưởng mẫu gốc.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        form.addRow(hint)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_cancel = QPushButton("Huỷ")
        btn_cancel.clicked.connect(self.reject)
        nav.addWidget(btn_cancel)
        btn_copy = QPushButton("Sao chép && mở để sửa")
        btn_copy.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        btn_copy.clicked.connect(self._do_copy)
        nav.addWidget(btn_copy)
        form.addRow(nav)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _do_copy(self):
        new_id = self.e_new_id.text().strip()
        if not new_id or not new_id.replace("_", "").isalnum():
            QMessageBox.warning(self, "Lỗi", "Mã mẫu mới chỉ được chứa chữ/số/gạch dưới, không để trống.")
            return
        if (TEMPLATES_DIR / new_id).exists():
            QMessageBox.warning(self, "Lỗi", f"Mẫu '{new_id}' đã tồn tại — hãy chọn mã khác.")
            return
        try:
            timport.copy_template(self.source_id, new_id, self.e_new_name.text().strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi sao chép", str(exc))
            return
        self.new_template_id = new_id
        self.accept()


# =============================================================================
# 2.5) Sao chép 1 bảng có sẵn (trong cùng 1 mẫu) thành bảng mới
# =============================================================================

class CopyTableDialog(QDialog):
    def __init__(self, tables_dir: Path, source_id: str, source_name: str, parent=None):
        super().__init__(parent)
        self.tables_dir = Path(tables_dir)
        self.source_id = source_id
        self.new_table_id = None

        self.setWindowTitle("Sao chép bảng")
        self.setMinimumSize(1500, 800)
        form = QFormLayout(self)

        lbl_source = QLabel(f"{source_id} — {source_name}")
        lbl_source.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        form.addRow("Bảng nguồn:", lbl_source)

        self.e_new_id = QLineEdit()
        self.e_new_id.setPlaceholderText(f"vd {source_id}b")
        form.addRow("Mã bảng mới:", self.e_new_id)

        self.e_new_name = QLineEdit(f"{source_name} (bản sao)")
        form.addRow("Tên bài test:", self.e_new_name)

        hint = QLabel("Sao chép nguyên vẹn toàn bộ dữ liệu dòng (kể cả cấu trúc nâng cao nếu có) — "
                       "bảng mới chưa gán kịch bản, tự gõ thêm tag report_val() tương ứng trong file .docx.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        form.addRow(hint)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_cancel = QPushButton("Huỷ")
        btn_cancel.clicked.connect(self.reject)
        nav.addWidget(btn_cancel)
        btn_copy = QPushButton("Sao chép")
        btn_copy.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        btn_copy.clicked.connect(self._do_copy)
        nav.addWidget(btn_copy)
        form.addRow(nav)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _do_copy(self):
        new_id = self.e_new_id.text().strip()
        err = wio.validate_table_id_available(self.tables_dir, new_id) if new_id else "Mã bảng không được để trống."
        if err:
            QMessageBox.warning(self, "Lỗi", err)
            return
        try:
            timport.copy_table(self.tables_dir, self.source_id, new_id, self.e_new_name.text().strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi sao chép", str(exc))
            return
        self.new_table_id = new_id
        self.accept()


# =============================================================================
# 3.5) Xem chi tiết 1 bảng — CHỈ ĐỌC, diễn giải tiếng Việt thay vì bắt user
# tự đọc JSON thô. Dùng cho CẢ bảng đơn giản lẫn nâng cao.
# =============================================================================

def _describe_row_structure(row_def) -> str:
    """Diễn giải bằng tiếng Việt cách 1 dòng tiêu thụ report_val() — bảng
    đơn giản chỉ 1 câu ngắn, bảng nâng cao giải thích rõ bao nhiêu report_val()
    là lần đo thật vs field kịch bản tự tính, và Độ KĐBĐ (nếu có) nằm ở đâu."""
    raw_count = row_def.raw_count
    if (row_def.measured_count is None and row_def.value_format_seq is None
            and row_def.uncertainty_index is None):
        if raw_count is None:
            return "Lấy HẾT report_val() còn lại của bảng (không giới hạn số lần đo)."
        if raw_count == 1:
            return "1 report_val() = 1 lần đo thật."
        return f"{raw_count} report_val() liên tiếp, TẤT CẢ đều là lần đo thật (tính trung bình)."

    total = raw_count if raw_count is not None else (row_def.measured_count or 0)
    measured = row_def.measured_count if row_def.measured_count is not None else total
    extra = total - measured
    text = f"{measured} report_val() ĐẦU là lần đo thật (dùng tính trung bình/công thức)"
    if extra > 0:
        text += f"; {extra} report_val() SAU do KỊCH BẢN TỰ TÍNH rồi đẩy thêm (vd sai số, TB, Độ KĐBĐ)"
    if row_def.uncertainty_index is not None:
        text += f". Độ KĐBĐ = report_val() thứ {row_def.uncertainty_index + 1}/{total}, hiện ra GCN qua gcn_limit()"
    return text + "."


def _parse_float_or_none(text: str, field_label: str, row_label: str):
    text = text.strip()
    if text in ("", "—"):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        raise ValueError(f"Dòng '{row_label}': {field_label} '{text}' không phải số hợp lệ.")


def _parse_int_or_none(text: str, field_label: str, row_label: str):
    text = text.strip()
    if text in ("", "—", "hết còn lại"):
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"Dòng '{row_label}': {field_label} '{text}' không phải số nguyên hợp lệ.")


class RowAdvancedDialog(QDialog):
    """Sửa 3 field 'nâng cao' của 1 dòng — measured_count/value_format_seq/
    uncertainty_index (core/table_descriptor.py::RowDef) — tách riêng khỏi
    bảng chính vì value_format_seq là 1 DANH SÁCH (1 định dạng/report_val()),
    không gõ vừa trong 1 ô bảng thường được."""

    def __init__(self, row_key: str, raw_count: int, adv: dict, default_format: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cấu trúc nâng cao — dòng '{row_key}'")
        self.setMinimumSize(1500, 800)
        self.raw_count = raw_count
        lay = QVBoxLayout(self)

        info = QLabel(f"Dòng này tiêu thụ {raw_count} report_val() liên tiếp.")
        info.setWordWrap(True)
        lay.addWidget(info)

        # -- measured_count --
        self.chk_all_measured = QRadioButton("Dùng HẾT report_val() để tính (không có phần kịch bản tự tính thêm)")
        self.chk_partial_measured = QRadioButton("Chỉ 1 số report_val() ĐẦU là đo thật, phần còn lại kịch bản tự tính")
        grp = QButtonGroup(self)
        grp.addButton(self.chk_all_measured)
        grp.addButton(self.chk_partial_measured)
        lay.addWidget(self.chk_all_measured)
        lay.addWidget(self.chk_partial_measured)
        mc_form = QFormLayout()
        self.sp_measured = QSpinBox()
        self.sp_measured.setRange(0, raw_count)
        self.sp_measured.setValue(adv["measured_count"] if adv["measured_count"] is not None else raw_count)
        mc_form.addRow("Số report_val() ĐẦU là đo thật:", self.sp_measured)
        lay.addLayout(mc_form)
        is_partial = adv["measured_count"] is not None
        self.chk_partial_measured.setChecked(is_partial)
        self.chk_all_measured.setChecked(not is_partial)
        self.sp_measured.setEnabled(is_partial)
        self.chk_partial_measured.toggled.connect(self.sp_measured.setEnabled)

        # -- value_format_seq --
        lay.addWidget(QLabel(""))
        self.chk_default_format = QRadioButton("Dùng ĐÚNG 1 định dạng mặc định của bảng cho mọi report_val()")
        self.chk_custom_format = QRadioButton("Đặt định dạng riêng cho từng report_val()")
        grp2 = QButtonGroup(self)
        grp2.addButton(self.chk_default_format)
        grp2.addButton(self.chk_custom_format)
        lay.addWidget(self.chk_default_format)
        lay.addWidget(self.chk_custom_format)

        seq_box = QWidget()
        seq_lay = QFormLayout(seq_box)
        current_seq = adv["value_format_seq"] or []
        self.format_combos = []
        for pos in range(raw_count):
            cur = current_seq[pos] if pos < len(current_seq) else default_format
            cb = _combo(wio.FORMAT_LABELS_ALL, current=cur)
            seq_lay.addRow(f"report_val() vị trí {pos + 1}:", cb)
            self.format_combos.append(cb)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(seq_box)
        scroller.setMaximumHeight(240)
        lay.addWidget(scroller)

        has_custom = adv["value_format_seq"] is not None
        self.chk_custom_format.setChecked(has_custom)
        self.chk_default_format.setChecked(not has_custom)
        seq_box.setEnabled(has_custom)
        self.chk_custom_format.toggled.connect(seq_box.setEnabled)

        # -- uncertainty_index --
        ui_form = QFormLayout()
        ui_items = [(None, "Không có")] + [(i, f"Vị trí {i + 1}") for i in range(raw_count)]
        self.cb_uncertainty = _combo(ui_items, current=adv["uncertainty_index"])
        ui_form.addRow("Độ KĐBĐ nằm ở report_val() nào:", self.cb_uncertainty)
        lay.addLayout(ui_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def result_values(self) -> dict:
        measured_count = self.sp_measured.value() if self.chk_partial_measured.isChecked() else None
        if self.chk_custom_format.isChecked():
            value_format_seq = [cb.currentData() for cb in self.format_combos]
        else:
            value_format_seq = None
        uncertainty_index = self.cb_uncertainty.currentData()
        return {
            "measured_count": measured_count,
            "value_format_seq": value_format_seq,
            "uncertainty_index": uncertainty_index,
        }


class TableDetailDialog(QDialog):
    """Xem VÀ SỬA chi tiết 1 bảng — mục tiêu giúp người dùng hiểu Ý NGHĨA
    từng thuộc tính cấu hình (pass_rule, measured_count, value_format_seq,
    uncertainty_index...) mà không cần tự đọc/đoán JSON thô, đồng thời sửa
    trực tiếp giá trị từng dòng (kể cả cấu trúc nâng cao) mà không cần mở
    file JSON bằng tay. 'Khoá' giữ CỐ ĐỊNH (không cho sửa) vì Scenario
    Builder tham chiếu tới field này — đổi sẽ làm gãy kịch bản đã gán."""

    def __init__(self, descriptor, tables_dir, parent=None):
        super().__init__(parent)
        self.descriptor = descriptor
        self.tables_dir = Path(tables_dir)
        self.changed = False
        self.setWindowTitle(f"Chi tiết bảng {descriptor.table_id}")
        self.setMinimumSize(1500, 800)
        layout = QVBoxLayout(self)

        info = QFormLayout()
        info.addRow("Mã bảng:", QLabel(descriptor.table_id))

        self.e_name = QLineEdit(descriptor.name)
        info.addRow("Tên bài test:", self.e_name)

        self.sp_order = QSpinBox()
        self.sp_order.setRange(1, 999)
        self.sp_order.setValue(descriptor.order)
        info.addRow("Thứ tự hiển thị:", self.sp_order)

        self.e_value_unit = QComboBox()
        self.e_value_unit.setEditable(True)
        self.e_value_unit.addItems(["Hz", "mVrms", "dBm", "s", "W"])
        self.e_value_unit.setEditText(descriptor.value_unit)
        info.addRow("Đơn vị giá trị đo:", self.e_value_unit)

        self.e_value_format = _combo(wio.FORMAT_LABELS_ALL, current=descriptor.value_format)
        info.addRow("Định dạng giá trị mặc định:", self.e_value_format)
        layout.addLayout(info)

        # -- quy tắc Đạt/Không đạt (giống TableFormDialog) --
        layout.addWidget(QLabel("Quy tắc Đạt/Không đạt:"))
        self.pr_group = QButtonGroup(self)
        self.pr_widgets = {}
        current_pr = descriptor.pass_rule.get("type", "none")
        for key, desc in wio.PASS_RULE_CHOICES:
            rb = QRadioButton(desc)
            rb.setProperty("pr_key", key)
            self.pr_group.addButton(rb)
            layout.addWidget(rb)
            extra = QWidget()
            extra_lay = QFormLayout(extra)
            extra.setVisible(False)
            if key == "relative_error_vs_fixed_limit":
                params = descriptor.pass_rule.get("params", {}) if current_pr == key else {}
                e_limit = QLineEdit(str(params.get("fixed_limit", "2.4e-7")))
                e_str = QLineEdit(params.get("limit_str", "± 2,4×10⁻⁷"))
                extra_lay.addRow("Ngưỡng sai số tương đối:", e_limit)
                extra_lay.addRow("Chuỗi hiển thị:", e_str)
                self.pr_widgets[key] = {"fixed_limit": e_limit, "limit_str": e_str, "extra": extra, "radio": rb}
            else:
                self.pr_widgets[key] = {"extra": extra, "radio": rb}
            rb.setChecked(key == current_pr)
            rb.toggled.connect(lambda checked, ex=extra: ex.setVisible(checked))
            extra.setVisible(key == current_pr)
            layout.addWidget(extra)
        if current_pr not in self.pr_widgets:
            self.pr_widgets["none"]["radio"].setChecked(True)

        self.advanced = wio.is_advanced_table(descriptor)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self._refresh_note()
        layout.addWidget(self.note)

        edit_hint = QLabel("Sửa trực tiếp các ô bên dưới rồi bấm \"💾 Lưu thay đổi\". "
                            "'Khoá' giữ cố định (Scenario Builder tham chiếu tới field này).")
        edit_hint.setWordWrap(True)
        edit_hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        layout.addWidget(edit_hint)

        self.tbl = QTableWidget(len(descriptor.rows), 8)
        self.tbl.setHorizontalHeaderLabels(
            ["Khoá", "Nhãn hiển thị", "Tần số thiết lập", "Chuẩn dùng để tính", "Ngưỡng",
             "Số report_val()", "Diễn giải", ""])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(6, self.tbl.horizontalHeader().Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(7, self.tbl.horizontalHeader().Fixed)
        self.tbl.horizontalHeader().resizeSection(7, 44)

        self._row_advanced = []
        for i, r in enumerate(descriptor.rows):
            key_item = QTableWidgetItem(r.key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            key_item.setToolTip("Khoá không sửa được — Scenario Builder tham chiếu tới field này.")
            self.tbl.setItem(i, 0, key_item)
            self.tbl.setItem(i, 1, QTableWidgetItem(r.display_label))
            self.tbl.setItem(i, 2, QTableWidgetItem(_num_str(r.freq_set) if r.freq_set is not None else ""))
            self.tbl.setItem(i, 3, QTableWidgetItem(_num_str(r.reference) if r.reference is not None else ""))
            self.tbl.setItem(i, 4, QTableWidgetItem(r.limit))
            self.tbl.setItem(i, 5, QTableWidgetItem(str(r.raw_count) if r.raw_count is not None else ""))

            self._row_advanced.append({
                "measured_count": r.measured_count,
                "value_format_seq": list(r.value_format_seq) if r.value_format_seq else None,
                "uncertainty_index": r.uncertainty_index,
            })

            memo = QTextEdit()
            memo.setReadOnly(True)
            memo.setPlainText(_describe_row_structure(r))
            memo.setFrameShape(QFrame.NoFrame)
            memo.setLineWrapMode(QTextEdit.WidgetWidth)
            memo.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            memo.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            memo.setStyleSheet("background: transparent;")
            self.tbl.setCellWidget(i, 6, memo)
            self.tbl.setRowHeight(i, 70)

            btn_adv = QPushButton("⚙")
            btn_adv.setToolTip("Sửa cấu trúc nâng cao (measured_count/value_format_seq/uncertainty_index)")
            btn_adv.setFixedWidth(36)
            btn_adv.clicked.connect(lambda _c=False, row=i: self._edit_advanced(row))
            self.tbl.setCellWidget(i, 7, btn_adv)

        self.tbl.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tbl, 1)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_save = QPushButton("💾 Lưu thay đổi")
        btn_save.clicked.connect(self._save)
        nav.addWidget(btn_save)
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        nav.addWidget(btn_close)
        layout.addLayout(nav)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _refresh_note(self):
        self.note.setText(
            "⚙ Bảng NÂNG CAO — có dòng nhận NHIỀU report_val() (không chỉ 1 lần đo/dòng). "
            "Xem cột \"Diễn giải\" bên dưới để biết rõ từng report_val() dùng vào việc gì."
            if self.advanced else
            "✓ Bảng ĐƠN GIẢN — mỗi dòng nhận đúng 1 report_val() (1 lần đo)."
        )
        self.note.setStyleSheet(
            f"color:{Colors.ACCENT_WARN if self.advanced else Colors.ACCENT_GREEN}; font-size:11px; padding:4px 0;")

    def _row_label(self, i: int) -> str:
        item = self.tbl.item(i, 1)
        label = item.text().strip() if item else ""
        return label or self.tbl.item(i, 0).text()

    def _raw_count_of_row(self, i: int):
        try:
            return _parse_int_or_none(self.tbl.item(i, 5).text(), "Số report_val()", self._row_label(i))
        except ValueError:
            return None

    def _edit_advanced(self, i: int):
        raw_count = self._raw_count_of_row(i)
        if raw_count is None:
            QMessageBox.warning(self, "Chưa thể sửa",
                                 "Đặt trước 'Số report_val()' (số cụ thể, khác 'hết còn lại') "
                                 "cho dòng này rồi mới sửa được cấu trúc nâng cao.")
            return
        dlg = RowAdvancedDialog(self._row_label(i), raw_count, self._row_advanced[i],
                                 self.descriptor.value_format, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._row_advanced[i] = dlg.result_values()
            self._refresh_row_memo(i)

    def _refresh_row_memo(self, i: int):
        try:
            row_def = self._current_row_def(i)
        except ValueError:
            return
        memo = self.tbl.cellWidget(i, 6)
        memo.setPlainText(_describe_row_structure(row_def))

        advanced = False
        for r in range(self.tbl.rowCount()):
            try:
                rd = self._current_row_def(r)
            except ValueError:
                continue
            if rd.measured_count is not None or rd.value_format_seq is not None or rd.uncertainty_index is not None:
                advanced = True
                break
        self.advanced = advanced
        self._refresh_note()

    def _on_item_changed(self, item):
        self._refresh_row_memo(item.row())

    def _current_row_def(self, i: int) -> RowDef:
        original = self.descriptor.rows[i]
        adv = self._row_advanced[i]
        return RowDef(
            key=original.key,
            freq_set=_parse_float_or_none(self.tbl.item(i, 2).text(), "Tần số thiết lập", self._row_label(i)),
            reference=_parse_float_or_none(self.tbl.item(i, 3).text(), "Chuẩn dùng để tính", self._row_label(i)),
            raw_count=_parse_int_or_none(self.tbl.item(i, 5).text(), "Số report_val()", self._row_label(i)),
            limit=self.tbl.item(i, 4).text().strip(),
            display_label=self.tbl.item(i, 1).text().strip(),
            measured_count=adv["measured_count"],
            value_format_seq=list(adv["value_format_seq"]) if adv["value_format_seq"] else None,
            uncertainty_index=adv["uncertainty_index"],
        )

    def _save(self):
        try:
            new_rows = [self._current_row_def(i) for i in range(self.tbl.rowCount())]
        except ValueError as exc:
            QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", str(exc))
            return

        name = self.e_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", "Tên bài test không được để trống.")
            return
        value_unit = self.e_value_unit.currentText().strip()
        value_format = self.e_value_format.currentData() or "text"

        pr_btn = self.pr_group.checkedButton()
        pr_key = pr_btn.property("pr_key") if pr_btn else "none"
        if pr_key == "relative_error_vs_fixed_limit":
            wdg = self.pr_widgets[pr_key]
            try:
                fixed_limit = float(wdg["fixed_limit"].text().strip().replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", "Ngưỡng sai số phải là số.")
                return
            limit_str = wdg["limit_str"].text().strip()
            if not limit_str:
                QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", "Chuỗi hiển thị ngưỡng không được để trống.")
                return
            pass_rule = {"type": pr_key, "params": {"fixed_limit": fixed_limit, "limit_str": limit_str}}
        else:
            pass_rule = {"type": pr_key}
            if pr_key == "value_vs_parsed_threshold" and not wio.pass_rule_allowed_for_unit(pr_key, value_unit):
                QMessageBox.warning(
                    self, "Dữ liệu chưa hợp lệ",
                    "Quy tắc 'So sánh với ngưỡng ghi từng dòng' chỉ dùng được với đơn vị mVrms/dBm.")
                return

        new_descriptor = _dc_replace(
            self.descriptor, name=name, order=self.sp_order.value(),
            value_unit=value_unit, value_format=value_format, pass_rule=pass_rule,
            rows=new_rows,
        )
        errs = validate_descriptor(new_descriptor)
        if errs:
            QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", "\n".join(errs))
            return

        try:
            timport.apply_table_to_existing(self.tables_dir, new_descriptor)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi lưu", str(exc))
            return

        self.descriptor = new_descriptor
        self.changed = True
        QMessageBox.information(self, "Đã lưu", f"Đã lưu bảng {new_descriptor.table_id}.")


# =============================================================================
# 4) Form 1 bảng "đơn giản" — thêm mới HOẶC sửa lại
# =============================================================================

class TableFormDialog(QDialog):
    def __init__(self, tables_dir: Path, existing, parent=None):
        """existing: TableDescriptor ĐÃ CÓ — sửa 1 bảng "đơn giản" (mỗi dòng
        đúng 1 report_val()). Không còn đường "thêm bảng mới rỗng" — bảng mới
        chỉ tạo qua sao chép 1 bảng có sẵn (xem CopyTableDialog)."""
        super().__init__(parent)
        self.tables_dir = tables_dir
        spec = wio.descriptor_to_spec(existing)

        self.setWindowTitle(f"Sửa bảng {existing.table_id}")
        self.setMinimumSize(1500, 800)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        w = QWidget()
        lay = QVBoxLayout(w)

        form = QFormLayout()
        self.e_table_id = QLineEdit(spec.table_id)
        self.e_table_id.setEnabled(False)   # không đổi mã bảng khi sửa (tag docx đã cố định)
        form.addRow("Mã bảng:", self.e_table_id)
        self.e_name = QLineEdit(spec.name)
        form.addRow("Tên bảng:", self.e_name)
        self.sp_order = QSpinBox()
        self.sp_order.setRange(1, 999)
        self.sp_order.setValue(spec.order)
        form.addRow("Thứ tự:", self.sp_order)
        self.e_value_unit = QComboBox()
        self.e_value_unit.setEditable(True)
        self.e_value_unit.addItems(["Hz", "mVrms", "dBm", "s", "W"])
        self.e_value_unit.setEditText(spec.value_unit)
        form.addRow("Đơn vị giá trị đo:", self.e_value_unit)
        self.e_value_format = _combo(wio.FORMAT_LABELS_ALL, current=spec.value_format)
        form.addRow("Định dạng giá trị (report_val()/gcn_avg()/gcn_error()):", self.e_value_format)
        lay.addLayout(form)

        # --- quy tắc đạt/không đạt ---
        lay.addWidget(QLabel("Quy tắc Đạt/Không đạt:"))
        self.pr_group = QButtonGroup(w)
        self.pr_widgets = {}
        current_pr = spec.pass_rule.get("type", "none")
        for key, desc in wio.PASS_RULE_CHOICES:
            rb = QRadioButton(desc)
            rb.setProperty("pr_key", key)
            self.pr_group.addButton(rb)
            lay.addWidget(rb)
            extra = QWidget()
            extra_lay = QFormLayout(extra)
            extra.setVisible(False)
            if key == "relative_error_vs_fixed_limit":
                params = spec.pass_rule.get("params", {}) if current_pr == key else {}
                e_limit = QLineEdit(str(params.get("fixed_limit", "2.4e-7")))
                e_str = QLineEdit(params.get("limit_str", "± 2,4×10⁻⁷"))
                extra_lay.addRow("Ngưỡng sai số tương đối:", e_limit)
                extra_lay.addRow("Chuỗi hiển thị:", e_str)
                self.pr_widgets[key] = {"fixed_limit": e_limit, "limit_str": e_str, "extra": extra, "radio": rb}
            else:
                self.pr_widgets[key] = {"extra": extra, "radio": rb}
            rb.setChecked(key == current_pr)
            rb.toggled.connect(lambda checked, ex=extra: ex.setVisible(checked))
            extra.setVisible(key == current_pr)
            lay.addWidget(extra)
        if current_pr not in self.pr_widgets:
            self.pr_widgets["none"]["radio"].setChecked(True)

        # --- dữ liệu từng dòng ---
        lay.addWidget(QLabel("Dữ liệu từng dòng (điểm đo cố định của bảng — đúng số dòng "
                              "bạn đã gõ report_val() trong file .docx):"))
        n_rows = len(spec.rows)
        self.rows_table = QTableWidget(max(n_rows, 1), 5)
        self.rows_table.setHorizontalHeaderLabels(
            ["Khoá", "Tần số thiết lập", "Chuẩn dùng để tính", "Ngưỡng", "Nhãn hiển thị"])
        self.rows_table.horizontalHeader().setStretchLastSection(True)
        for i, r in enumerate(spec.rows):
            self.rows_table.setItem(i, 0, QTableWidgetItem(r.key))
            self.rows_table.setItem(i, 1, QTableWidgetItem(
                "" if r.freq_set is None else _num_str(r.freq_set)))
            self.rows_table.setItem(i, 2, QTableWidgetItem(
                "" if r.reference is None else _num_str(r.reference)))
            self.rows_table.setItem(i, 3, QTableWidgetItem(r.limit))
            self.rows_table.setItem(i, 4, QTableWidgetItem(r.display_label))

        def _add_row():
            self.rows_table.insertRow(self.rows_table.rowCount())
            _fit_table_height(self.rows_table)

        def _del_row():
            if self.rows_table.currentRow() >= 0:
                self.rows_table.removeRow(self.rows_table.currentRow())
                _fit_table_height(self.rows_table)

        row_btns = QHBoxLayout()
        btn_add_row = QPushButton("+ Thêm dòng")
        btn_add_row.clicked.connect(_add_row)
        row_btns.addWidget(btn_add_row)
        btn_del_row = QPushButton("− Xoá dòng đang chọn")
        btn_del_row.clicked.connect(_del_row)
        row_btns.addWidget(btn_del_row)
        btn_copy_ref = QPushButton("Chuẩn = Tần số thiết lập (áp cho mọi dòng)")

        def _copy_freq_to_ref():
            for i in range(self.rows_table.rowCount()):
                freq_item = self.rows_table.item(i, 1)
                self.rows_table.setItem(i, 2, QTableWidgetItem(freq_item.text() if freq_item else ""))
        btn_copy_ref.clicked.connect(_copy_freq_to_ref)
        row_btns.addWidget(btn_copy_ref)
        row_btns.addStretch()
        lay.addLayout(row_btns)
        _fit_table_height(self.rows_table)
        lay.addWidget(self.rows_table)

        lay.addStretch()
        scroller.setWidget(w)

        outer = QVBoxLayout(self)
        outer.addWidget(scroller, 1)
        nav = QHBoxLayout()
        nav.addStretch()
        btn_cancel = QPushButton("Huỷ")
        btn_cancel.clicked.connect(self.reject)
        nav.addWidget(btn_cancel)
        btn_save = QPushButton("💾 Lưu")
        btn_save.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        btn_save.clicked.connect(self._do_save)
        nav.addWidget(btn_save)
        outer.addLayout(nav)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _do_save(self):
        table_id = self.e_table_id.text().strip()
        name = self.e_name.text().strip()
        value_unit = self.e_value_unit.currentText().strip()
        value_format = self.e_value_format.currentData() or "text"

        pr_btn = self.pr_group.checkedButton()
        pr_key = pr_btn.property("pr_key") if pr_btn else "none"
        if pr_key == "relative_error_vs_fixed_limit":
            wdg = self.pr_widgets[pr_key]
            try:
                fixed_limit = float(wdg["fixed_limit"].text().strip().replace(",", "."))
            except ValueError:
                QMessageBox.warning(self, "Lỗi", "Ngưỡng sai số phải là số.")
                return
            limit_str = wdg["limit_str"].text().strip()
            if not limit_str:
                QMessageBox.warning(self, "Lỗi", "Chuỗi hiển thị ngưỡng không được để trống.")
                return
            pass_rule = {"type": pr_key, "params": {"fixed_limit": fixed_limit, "limit_str": limit_str}}
        else:
            pass_rule = {"type": pr_key}
            if pr_key == "value_vs_parsed_threshold" and not wio.pass_rule_allowed_for_unit(pr_key, value_unit):
                QMessageBox.warning(
                    self, "Lỗi",
                    "Quy tắc 'So sánh với ngưỡng ghi từng dòng' chỉ dùng được với đơn vị mVrms/dBm.")
                return

        rows = []
        for i in range(self.rows_table.rowCount()):
            def _cell(col):
                item = self.rows_table.item(i, col)
                return item.text().strip() if item else ""
            key = _cell(0)
            freq_text, ref_text = _cell(1), _cell(2)
            freq_set = wio.guess_bare_number(freq_text) if freq_text else None
            reference = wio.guess_bare_number(ref_text) if ref_text else None
            if ref_text and reference is None:
                QMessageBox.warning(self, "Lỗi", f"Dòng {i + 1}: 'Chuẩn dùng để tính' phải là số.")
                return None
            rows.append(wio.WizardRowSpec(key=key, freq_set=freq_set, reference=reference,
                                           limit=_cell(3), display_label=_cell(4)))

        err = wio.validate_rows(rows, pass_rule)
        if err:
            QMessageBox.warning(self, "Lỗi", err)
            return

        spec = wio.WizardTableSpec(
            table_id=table_id, name=name, order=self.sp_order.value(),
            value_unit=value_unit, value_format=value_format,
            rows=rows, pass_rule=pass_rule, gcn=None,
        )
        try:
            descriptor = wio.build_descriptor(spec)
            timport.apply_table_to_existing(self.tables_dir, descriptor)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi lưu", str(exc))
            return
        self.accept()


def _num_str(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return str(v)
