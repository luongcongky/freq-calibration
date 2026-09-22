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
    QListWidget, QListWidgetItem, QSplitter, QStackedWidget, QCheckBox,
    QHeaderView, QAbstractItemView,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

from gui.theme import Colors
from gui.file_dialog_utils import get_open_file_name
from gui.widgets import paint_corner_brackets
from core import table_wizard_io as wio
from core import xlsx_wizard_io as xwio
from core import table_import as timport
from core.report_templates import list_templates
from core.report_templates.generic import TEMPLATES_DIR, template_summary
from core.table_descriptor import RowDef, TableDescriptor, load_table_descriptors, validate_descriptor

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

  (b) {{ tables.<Mã bảng>.gcn_avg() }}     report_val() ĐẦU TIÊN của dòng
      {{ tables.<Mã bảng>.gcn_error() }}   số hiệu chỉnh (chuẩn − giá trị trên)
      {{ tables.<Mã bảng>.gcn_limit() }}   ngưỡng của dòng (nếu có khai báo)
      Dùng cho văn bản HIỆU CHUẨN (pass_rule correction_vs_reference) —
      phần mềm KHÔNG tự tính trung bình nữa, chỉ đọc lại ĐÚNG report_val()
      Biên Bản đã đẩy (kịch bản tự tính trung bình trước khi đẩy, nếu cần).

      Ví dụ minh hoạ — mẫu TEMPLATE_POWER, bảng A1 (pass_rule
      correction_vs_reference, value_format "w", dòng "1 mW" đẩy >1
      report_val() nên gcn_limit() ở đây trả về ĐÚNG report_val() CUỐI CÙNG
      (Độ KĐBĐ kịch bản đã tự tính rồi đẩy thêm), không phải ngưỡng tĩnh):
        {{ tables.A1.gcn_avg() }}     -> report_val() đầu tiên, format "w" (vd "0,001021 W")
        {{ tables.A1.gcn_error() }}   -> tự format correction_mw (auto suy từ value_format="w")
        {{ tables.A1.gcn_limit() }}   -> Độ KĐBĐ = report_val() CUỐI CÙNG kịch bản tự tính
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


def _clear_layout(layout) -> None:
    """Xoá sạch mọi item con (widget lẫn layout lồng nhau) của `layout`,
    KHÔNG xoá bản thân `layout` — dùng để dựng lại nội dung 1 vùng khi cần
    refresh (vd ImportTableFromExcelDialog đọc lại vùng dữ liệu) mà không
    phải remove/insertWidget trên layout CHA (đã gặp lỗi Qt hiếm gặp làm
    hỏng phần vẽ của các item khác đứng trước trong cùng layout cha đó)."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _combo(items, current=None) -> QComboBox:
    cb = QComboBox()
    for value, label in items:
        cb.addItem(label, value)
    # 1 vài lựa chọn có nhãn RẤT dài (vd "★ Giá trị đo (CHỈ NHẬN DIỆN...)")
    # — mặc định QComboBox tự giãn rộng theo ĐÚNG lựa chọn dài nhất trong
    # danh sách (kể cả lựa chọn đó không đang được chọn), kéo theo cả layout
    # cha bị ép rộng ra và xuất hiện thanh cuộn ngang không mong muốn (đã
    # gặp thật ở "Đọc bảng từ Excel/Word" — 7+ combobox cùng lúc). Giới hạn
    # độ rộng hiển thị theo số ký tự cố định, chữ dài thì tự hiện "…" —
    # xem đầy đủ qua tooltip (cập nhật theo lựa chọn đang chọn) hoặc mở
    # dropdown ra xem (popup vẫn hiện đủ chữ, không bị cắt).
    cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
    cb.setMinimumContentsLength(24)

    def _sync_tooltip(i):
        cb.setToolTip(cb.itemText(i))
    cb.currentIndexChanged.connect(_sync_tooltip)

    if current is not None:
        idx = cb.findData(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
    _sync_tooltip(cb.currentIndex())
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
        self.changed_ids: set[str] = set()  # mã các mẫu THỰC SỰ bị sửa nội dung (không tính sao chép)
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
        self.tabs.addTab(QWidget(), "1. Thông tin chung")
        self.tabs.addTab(QWidget(), "2. File Word")
        self.tabs.addTab(QWidget(), "3. Bảng dữ liệu")
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
        self.changed_ids.add(tid)
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
        # _swap_tab() dựng lại tab bằng removeTab()+insertTab() — nếu tab
        # đang ACTIVE nằm trong số bị dựng lại (vd tab 2 "Bảng dữ liệu" sau
        # khi Xoá 1 bảng), Qt mất dấu tab hiện tại lúc removeTab() và rơi về
        # tab liền trước thay vì quay lại đúng tab -> phải tự lưu/khôi phục
        # currentIndex().
        current = self.tabs.currentIndex()
        self._swap_tab(0, self._build_meta_tab(), "1. Thông tin chung")
        self._swap_tab(1, self._build_docx_tab(), "2. File Word")
        self._swap_tab(2, self._build_tables_tab(), f"3. Bảng dữ liệu ({len(self._descriptors)})")
        if current >= 0:
            self.tabs.setCurrentIndex(current)
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
        if self.template_id:
            self.changed_ids.add(self.template_id)

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
        inner = QWidget()
        lay = QVBoxLayout(inner)

        toolbar = QHBoxLayout()
        btn_import = QPushButton("🔍 Đọc bảng từ Biên Bản…")
        btn_import.setToolTip(
            "Đọc các bảng khách đã tự dựng sẵn trong bienban.docx/bienban.xlsx — tự sinh dữ liệu "
            "từng dòng theo cấu trúc ô THẬT. Chỉ NHẬN DIỆN ô đã có sẵn tag report_val() do bạn tự "
            "gõ tay trong file, không tự động ghi/gán vào ô rỗng hay ô khác.")
        btn_import.clicked.connect(self._import_table)
        toolbar.addWidget(btn_import)
        toolbar.addStretch()
        lay.addLayout(toolbar)

        tbl = QTableWidget(len(self._descriptors), 5)
        tbl.setHorizontalHeaderLabels(["Mã", "Tên bài test", "", "", ""])
        tbl.horizontalHeader().setStretchLastSection(False)
        tbl.horizontalHeader().setSectionResizeMode(1, tbl.horizontalHeader().Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)

        for i, d in enumerate(self._descriptors):
            tbl.setItem(i, 0, QTableWidgetItem(d.table_id))
            tbl.setItem(i, 1, QTableWidgetItem(d.name))

            btn = QPushButton("✏️ Sửa")
            btn.clicked.connect(lambda _c=False, tid=d.table_id: self._edit_table(tid))
            tbl.setCellWidget(i, 2, btn)

            btn_copy = QPushButton("📋 Copy")
            btn_copy.setToolTip("Sao chép bảng này thành bảng mới")
            btn_copy.clicked.connect(lambda _c=False, tid=d.table_id, name=d.name: self._copy_table(tid, name))
            tbl.setCellWidget(i, 3, btn_copy)

            btn_del = QPushButton("🗑 Xoá")
            btn_del.setToolTip("Xoá bảng này")
            btn_del.setStyleSheet(f"color:{Colors.ACCENT_RED};")
            btn_del.clicked.connect(lambda _c=False, tid=d.table_id, name=d.name: self._delete_table(tid, name))
            tbl.setCellWidget(i, 4, btn_del)

        tbl.resizeColumnsToContents()
        _fit_table_height(tbl)
        lay.addWidget(tbl)

        lay.addStretch()

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidget(inner)
        return scroller

    def _edit_table(self, table_id: str):
        existing = next((d for d in self._descriptors if d.table_id == table_id), None)
        if existing is None:
            return
        # raw_count/value_format_seq giữ ĐÚNG NGUYÊN theo từng dòng đã có
        # (không còn bắt buộc đồng nhất giữa các dòng — 1 dòng tổng hợp gộp
        # ô có thể có raw_count khác các dòng còn lại, xem
        # core/table_wizard_io.py::raw_counts_for_measured_cols) — form vẫn
        # sửa được bình thường, chỉ ẩn nút "Sửa cấu trúc report_val()" nếu
        # các dòng không cùng 1 số (TableFormDialog tự xử lý).
        raw_counts = [r.raw_count or 1 for r in existing.rows]
        row_value_format_seqs = [list(r.value_format_seq) if r.value_format_seq else None
                                  for r in existing.rows]
        row_advanced = None
        if len(set(raw_counts)) == 1 and raw_counts and raw_counts[0] > 1:
            row_advanced = {"value_format_seq": row_value_format_seqs[0]}
        dlg = TableFormDialog(self.tables_dir, wio.descriptor_to_spec(existing),
                               raw_counts=raw_counts, row_advanced=row_advanced,
                               row_value_format_seqs=row_value_format_seqs,
                               bienban_path=self._resolve_doc_path("bienban"),
                               xlsx_ref=existing.xlsx_ref, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._mark_changed()
            self._load_template(self.template_id)

    def _import_table(self):
        xlsx_path = self.tpl_dir / "bienban.xlsx"
        docx_path = self.tpl_dir / "bienban.docx"
        if xlsx_path.exists():
            dlg = ImportTableFromExcelDialog(self.tables_dir, xlsx_path, self._descriptors, parent=self)
        elif docx_path.exists():
            dlg = ImportTableFromWordDialog(self.tables_dir, docx_path, self._descriptors, parent=self)
        else:
            QMessageBox.warning(self, "Chưa có file mẫu",
                                 "Mẫu này chưa có file bienban.docx hoặc bienban.xlsx.")
            return
        dlg.exec_()
        if dlg.imported_any:
            self._mark_changed()
            self._load_template(self.template_id)

    def _copy_table(self, table_id: str, table_name: str):
        dlg = CopyTableDialog(self.tables_dir, table_id, table_name, parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.new_table_id:
            self._mark_changed()
            self._load_template(self.template_id)

    def _delete_table(self, table_id: str, table_name: str):
        msg = (f"Xoá bảng '{table_id} — {table_name}'?\n\n"
               f"File JSON sẽ chuyển vào Thùng rác Windows (khôi phục được nếu lỡ tay), "
               f"nhưng tag report_val() còn tham chiếu bảng này trong file Word sẽ không render được nữa.")
        if QMessageBox.question(self, "Xác nhận xoá bảng", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            timport.delete_table(self.tables_dir, table_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi xoá", str(exc))
            return
        self._mark_changed()
        self._load_template(self.template_id)

    # -- Tab 3: File Word ----------------------------------------------------

    def _resolve_doc_path(self, which: str) -> Path:
        """File mẫu thật của `which` ('bienban'|'gcnkd') — thử .xlsx trước
        .docx (đúng thứ tự ưu tiên của core/report_templates/generic.py),
        mặc định .docx nếu mẫu chưa có file nào (hiển thị "chưa có file")."""
        for ext in (".xlsx", ".docx"):
            p = self.tpl_dir / f"{which}{ext}"
            if p.exists():
                return p
        return self.tpl_dir / f"{which}.docx"

    def _build_docx_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)

        for which, label in (("bienban", "Biên Bản (Phụ lục A)"), ("gcnkd", "Giấy Chứng Nhận (Phụ lục B)")):
            path = self._resolve_doc_path(which)
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
        path, _ = get_open_file_name(self, "Chọn file mẫu đã gắn tag sẵn", "",
                                      "Word/Excel (*.docx *.xlsx)")
        if not path:
            return
        ids = [d.table_id for d in self._descriptors]
        is_xlsx = Path(path).suffix.lower() == ".xlsx"
        missing = xwio.find_missing_table_ids(path, ids) if is_xlsx else wio.find_missing_table_ids(path, ids)
        if missing:
            needle = "report_val('<ID>')" if is_xlsx else "tables.<ID>"
            msg = (f"Không thấy '{needle}' của {missing} trong file vừa chọn.\n\n"
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
    đơn giản chỉ 1 câu ngắn, bảng nâng cao giải thích rõ report_val() nào
    dùng cho công thức Đạt/Không đạt, report_val() nào chỉ hiển thị lại
    (kịch bản đã tự tính sẵn — phần mềm không tự tính trung bình/Độ KĐBĐ
    nữa, xem core/table_engine.py::apply_pass_rule)."""
    raw_count = row_def.raw_count
    if raw_count is None:
        return "Lấy HẾT report_val() còn lại của bảng (không giới hạn số lần đo)."
    if raw_count == 1:
        return "1 report_val() = 1 giá trị đo dùng cho công thức Đạt/Không đạt."
    return (f"{raw_count} report_val() liên tiếp — report_val() ĐẦU TIÊN dùng cho công thức "
            f"Đạt/Không đạt; {raw_count - 1} report_val() SAU chỉ hiển thị lại nguyên văn (kịch bản "
            f"đã tự tính sẵn, vd trung bình/sai số). Nếu bảng dùng quy tắc 'Tính số hiệu chỉnh', "
            f"report_val() CUỐI CÙNG tự động là Độ KĐBĐ hiện ra GCN qua gcn_limit().")


class RowAdvancedDialog(QDialog):
    """Sửa định dạng riêng (value_format_seq) cho 1 dòng nhận NHIỀU
    report_val() liên tiếp (core/table_descriptor.py::RowDef) — tách riêng
    khỏi bảng chính vì value_format_seq là 1 DANH SÁCH (1 định dạng/
    report_val()), không gõ vừa trong 1 ô bảng thường được.

    Phần mềm KHÔNG tự tính trung bình/Độ KĐBĐ nữa: report_val() ĐẦU TIÊN
    luôn là giá trị dùng cho công thức Đạt/Không đạt, các report_val() sau
    chỉ hiển thị lại nguyên văn (kịch bản đã tự tính sẵn)."""

    def __init__(self, row_key: str, raw_count: int, adv: dict, default_format: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Định dạng report_val() — dòng '{row_key}'")
        self.setMinimumSize(900, 320)
        self.raw_count = raw_count
        lay = QVBoxLayout(self)

        info = QLabel(f"Dòng này tiêu thụ {raw_count} report_val() liên tiếp — report_val() ĐẦU TIÊN "
                       f"dùng cho công thức Đạt/Không đạt, các report_val() sau chỉ hiển thị lại nguyên "
                       f"văn (kịch bản đã tự tính sẵn).")
        info.setWordWrap(True)
        lay.addWidget(info)

        # -- value_format_seq --
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

        lay.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def result_values(self) -> dict:
        if self.chk_custom_format.isChecked():
            value_format_seq = [cb.currentData() for cb in self.format_combos]
        else:
            value_format_seq = None
        return {"value_format_seq": value_format_seq}


# =============================================================================
# 3.5) Đọc bảng từ Word — khách đã tự dựng sẵn bảng thật trong bienban.docx,
#      chỉ chừa trống ô sẽ chứa giá trị đo. CHỈ đọc text ô có sẵn để suy ra
#      dữ liệu dòng + hỏi khách gán ý nghĩa từng cột qua dropdown, rồi mở
#      TableFormDialog (is_new=True) để khách xác nhận trước khi lưu + tự gõ
#      tag report_val() vào đúng ô đã chọn (core/table_wizard_io.py).
# =============================================================================

class ImportTableFromWordDialog(QDialog):
    def __init__(self, tables_dir: Path, docx_path: Path, existing_descriptors: list, parent=None):
        super().__init__(parent)
        self.tables_dir = tables_dir
        self.docx_path = docx_path
        self.existing_descriptors = existing_descriptors
        self.imported_any = False

        self.setWindowTitle("Đọc bảng từ file Word")
        self.setMinimumSize(1300, 750)

        self._detected = wio.scan_docx_tables(docx_path)

        root = QVBoxLayout(self)

        if not self._detected:
            root.addWidget(QLabel("Không tìm thấy bảng nào trong file Word này."))
            btn_close = QPushButton("Đóng")
            btn_close.clicked.connect(self.reject)
            root.addWidget(btn_close, alignment=Qt.AlignRight)
            return

        self.splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Bảng phát hiện được trong file:"))
        self.list_tables = QListWidget()
        self.splitter.addWidget(left)
        ll.addWidget(self.list_tables, 1)

        # QStackedWidget — mỗi bảng phát hiện được có 1 "trang" riêng dựng sẵn,
        # chọn ở list trái chỉ đổi trang hiện hành (setCurrentIndex), KHÔNG
        # thay widget bên trong QSplitter lúc chạy (từng dùng
        # QSplitter.replaceWidget() nhưng widget mới không tự hiện ra — đây là
        # cách chuẩn/ổn định hơn cho kiểu "chọn trái, đổi nội dung phải").
        self.stack = QStackedWidget()
        self.splitter.addWidget(self.stack)
        self.splitter.setSizes([320, 980])
        root.addWidget(self.splitter, 1)
        self.list_tables.currentRowChanged.connect(self.stack.setCurrentIndex)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        nav.addWidget(btn_close)
        root.addLayout(nav)

        self._refresh_list()

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _refresh_list(self):
        cur = max(self.list_tables.currentRow(), 0)
        self.list_tables.blockSignals(True)
        self.list_tables.clear()
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.deleteLater()
        for d in self._detected:
            suffix = "  ✓ đã có tag" if d.already_tagged else ""
            item = QListWidgetItem(f"Bảng #{d.index + 1} — {d.n_rows} dòng × {d.n_cols} cột{suffix}")
            if d.already_tagged:
                item.setForeground(QColor(Colors.TEXT_DIM))
            self.list_tables.addItem(item)
            self.stack.addWidget(self._build_editor(d))
        self.list_tables.blockSignals(False)
        if self.list_tables.count():
            idx = min(cur, self.list_tables.count() - 1)
            self.list_tables.setCurrentRow(idx)
            self.stack.setCurrentIndex(idx)

    def _suggest_table_id(self) -> str:
        used = {d.table_id for d in self.existing_descriptors}
        n = 1
        while f"A{n}" in used:
            n += 1
        return f"A{n}"

    def _build_editor(self, detected) -> QWidget:
        """Mỗi bảng phát hiện được có 1 trang riêng (QStackedWidget), nên các
        widget nhập liệu KHÔNG lưu trên self (self chỉ có 1 bản, sẽ bị bảng
        cuối cùng ghi đè) — giữ cục bộ rồi bind thẳng vào _continue() qua
        closure của nút Tiếp tục."""
        w = QWidget()
        lay = QVBoxLayout(w)

        form_top = QFormLayout()
        e_table_id = QLineEdit(self._suggest_table_id())
        form_top.addRow("Mã bảng:", e_table_id)
        e_name = QLineEdit()
        form_top.addRow("Tên bài test:", e_name)
        lay.addLayout(form_top)

        if detected.already_tagged:
            info = QLabel("✓ Bảng này đã có sẵn tag report_val() — những ô đó sẽ được NHẬN DIỆN "
                          "khi bấm Tiếp tục (xem chi tiết ở gợi ý dưới cột \"★ Giá trị đo\").")
            info.setWordWrap(True)
            info.setStyleSheet(f"color:{Colors.ACCENT_GREEN};")
            lay.addWidget(info)

        lbl_preview_hint = QLabel(
            "Xem trước nội dung đọc được từ Word (chỉ đọc, không sửa gì trong file) — dòng nào KHÔNG "
            "có sẵn tag report_val() trong (các) cột \"★ Giá trị đo\" tự động được coi là chữ tĩnh "
            "(vd dòng tiêu đề), KHÔNG tính là dòng dữ liệu:")
        lbl_preview_hint.setWordWrap(True)
        lay.addWidget(lbl_preview_hint)
        preview = QTableWidget(detected.n_rows, detected.n_cols)
        preview.setEditTriggers(QTableWidget.NoEditTriggers)
        preview.verticalHeader().setVisible(False)
        preview.setHorizontalHeaderLabels([f"Cột {c + 1}" for c in range(detected.n_cols)])
        for r, row_texts in enumerate(detected.grid):
            for c, text in enumerate(row_texts):
                item = QTableWidgetItem(text)
                if r == 0:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                preview.setItem(r, c, item)
        preview.resizeColumnsToContents()
        preview.setMaximumHeight(220)
        lay.addWidget(preview)

        lay.addWidget(QLabel("Mỗi cột trong bảng trên nghĩa là gì? (dựa theo dòng tiêu đề):"))
        role_form = QFormLayout()
        role_combos = []
        header_texts = detected.grid[0] if detected.grid else []
        for c in range(detected.n_cols):
            header_text = header_texts[c] if c < len(header_texts) else ""
            cb = _combo(wio.COLUMN_ROLE_CHOICES, current=wio.guess_column_role(header_text))
            role_form.addRow(f"Cột {c + 1} (\"{header_text}\"):", cb)
            role_combos.append(cb)
        lay.addLayout(role_form)

        lay.addStretch()
        btn_continue = QPushButton("Tiếp tục →")
        btn_continue.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        btn_continue.clicked.connect(
            lambda _c=False, d=detected, tid=e_table_id, nm=e_name, rc=role_combos:
                self._continue(d, tid, nm, rc))
        lay.addWidget(btn_continue, alignment=Qt.AlignRight)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidget(w)
        return scroller

    def _continue(self, detected, e_table_id, e_name, role_combos):
        table_id = e_table_id.text().strip()
        err = wio.validate_table_id_available(self.tables_dir, table_id)
        if err:
            QMessageBox.warning(self, "Lỗi", err)
            return
        name = e_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Lỗi", "Cần nhập Tên bài test.")
            return

        role_map = {i: cb.currentData() for i, cb in enumerate(role_combos)}
        measured_cols = sorted(i for i, r in role_map.items() if r == "measured")
        if not measured_cols:
            QMessageBox.warning(
                self, "Lỗi",
                "Phải chọn ÍT NHẤT 1 cột là '★ Giá trị đo (chỉ nhận diện ô đã có sẵn report_val())'.")
            return

        # KHÔNG ghi gì vào file — chỉ ĐẾM số ô đã có sẵn ĐÚNG tag
        # {{ tables.<table_id>.report_val() }} trong (các) cột "★ Giá trị
        # đo" đã chọn, CHO MỌI DÒNG của bảng (header_row_index=-1: không
        # loại dòng nào trước — xem docstring core/table_wizard_io.py::
        # raw_counts_for_measured_cols). Dòng nào đếm được 0 -> TỰ ĐỘNG coi
        # là chữ tĩnh (vd dòng tiêu đề) và bỏ qua, không cần khách khai báo
        # dòng nào là tiêu đề. Số report_val()/dòng CÓ THỂ KHÁC NHAU giữa
        # các dòng — 1 dòng tổng hợp (vd "Trung Bình") gộp nhiều cột thành 1
        # ô rộng thì chỉ cần 1 tag đã gõ, không phải N.
        all_counts = wio.raw_counts_for_measured_cols(
            self.docx_path, detected.index, measured_cols, table_id,
            header_row_index=-1, extra_skip_rows=frozenset())
        skip_relative = frozenset(i for i, c in enumerate(all_counts) if c == 0)
        raw_counts = [c for c in all_counts if c > 0]

        rows = wio.build_rows_from_grid(detected.grid, role_map, header_row_index=-1,
                                        extra_skip_rows=skip_relative)
        if not rows:
            QMessageBox.warning(
                self, "Chưa tìm thấy tag nào",
                f"Không tìm thấy ô nào đã có sẵn tag {{{{ tables.{table_id}.report_val() }}}} trong "
                f"(các) cột \"★ Giá trị đo\" đã chọn — không có dòng dữ liệu nào để nhận diện.\n\nHãy "
                f"tự gõ tag đó vào các ô dữ liệu tương ứng trong Word rồi bấm \"Tiếp tục →\" lại.")
            return

        # Nút "⚙ nâng cao" (định dạng riêng từng report_val()) CHỈ hiện khi
        # mọi dòng CÙNG 1 số report_val() — TableFormDialog tự ẩn nếu không,
        # cùng nguyên tắc "ẩn nâng cao" như Quy tắc Đạt/Không đạt: không ép
        # mở dialog hỏi ngay, không bắt buộc phải hiểu để nhập xong 1 bảng.
        row_advanced = ({"value_format_seq": None}
                        if len(set(raw_counts)) == 1 and raw_counts and raw_counts[0] > 1
                        else None)

        spec = wio.WizardTableSpec(
            table_id=table_id, name=name, order=len(self.existing_descriptors) + 1,
            value_unit="", value_format="text", rows=rows,
            pass_rule={"type": "none"}, gcn=None,
        )
        tag_target = {
            "kind": "docx",
            "docx_path": self.docx_path, "table_index": detected.index,
            "measured_cols": measured_cols, "header_row_index": -1,
            "extra_skip_rows": skip_relative,
        }
        dlg = TableFormDialog(self.tables_dir, spec, is_new=True, tag_target=tag_target,
                               raw_counts=raw_counts, row_advanced=row_advanced, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.imported_any = True
            self._detected = wio.scan_docx_tables(self.docx_path)
            self._refresh_list()


# =============================================================================
#      ImportTableFromExcelDialog — tương đương ImportTableFromWordDialog
#      nhưng file mẫu là .xlsx: khách tự khoanh 1 vùng ô (Excel không có
#      ranh giới bảng rõ như doc.tables). Cột "★ Giá trị đo" chỉ dùng để
#      khoanh vùng TÌM những ô khách đã TỰ GÕ TAY report_val('<id>') từ
#      trước trong Excel — CÙNG nguyên tắc "chỉ nhận diện, không tự ghi"
#      với ImportTableFromWordDialog (xem core/xlsx_wizard_io.py::
#      raw_counts_for_measured_cols) — quyết định thiết kế đã chốt với
#      khách hàng, tránh rủi ro ghi đè ngoài ý muốn lên file bảng tính có
#      công thức phức tạp.
# =============================================================================


class ImportTableFromExcelDialog(QDialog):
    def __init__(self, tables_dir: Path, xlsx_path: Path, existing_descriptors: list, parent=None):
        super().__init__(parent)
        self.tables_dir = tables_dir
        self.xlsx_path = xlsx_path
        self.existing_descriptors = existing_descriptors
        self.imported_any = False

        self.setWindowTitle("Đọc bảng từ file Excel")
        self.setMinimumSize(1300, 750)

        self._sheets = xwio.list_sheets(xlsx_path)

        root = QVBoxLayout(self)

        if not self._sheets:
            root.addWidget(QLabel("Không tìm thấy sheet nào trong file Excel này."))
            btn_close = QPushButton("Đóng")
            btn_close.clicked.connect(self.reject)
            root.addWidget(btn_close, alignment=Qt.AlignRight)
            return

        self.splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Sheet trong file:"))
        self.list_sheets = QListWidget()
        self.splitter.addWidget(left)
        ll.addWidget(self.list_sheets, 1)

        self.stack = QStackedWidget()
        self.splitter.addWidget(self.stack)
        self.splitter.setSizes([320, 980])
        root.addWidget(self.splitter, 1)
        self.list_sheets.currentRowChanged.connect(self.stack.setCurrentIndex)

        nav = QHBoxLayout()
        nav.addStretch()
        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.accept)
        nav.addWidget(btn_close)
        root.addLayout(nav)

        self._refresh_list()

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _refresh_list(self):
        cur = max(self.list_sheets.currentRow(), 0)
        self.list_sheets.blockSignals(True)
        self.list_sheets.clear()
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.deleteLater()
        for sheet in self._sheets:
            suffix = "  ✓ có vẻ đã có tag" if sheet.already_tagged else ""
            item = QListWidgetItem(f"{sheet.sheet_name} — vùng dùng {sheet.used_range}{suffix}")
            if sheet.already_tagged:
                item.setForeground(QColor(Colors.TEXT_DIM))
            self.list_sheets.addItem(item)
            self.stack.addWidget(self._build_editor(sheet))
        self.list_sheets.blockSignals(False)
        if self.list_sheets.count():
            idx = min(cur, self.list_sheets.count() - 1)
            self.list_sheets.setCurrentRow(idx)
            self.stack.setCurrentIndex(idx)

    def _suggest_table_id(self) -> str:
        used = {d.table_id for d in self.existing_descriptors}
        n = 1
        while f"A{n}" in used:
            n += 1
        return f"A{n}"

    def _build_editor(self, sheet) -> QWidget:
        """Khác ImportTableFromWordDialog._build_editor(): Excel không có
        ranh giới bảng cố định như doc.tables, nên khách tự gõ/sửa 'Vùng dữ
        liệu' rồi bấm "Đọc lại vùng này" để dựng lại preview + role dropdown
        — có thể lặp lại nhiều lần trước khi "Tiếp tục". `state` (dict, MỘT
        bản/trang) giữ dữ liệu của LẦN ĐỌC GẦN NHẤT để nút Tiếp tục dùng."""
        w = QWidget()
        lay = QVBoxLayout(w)

        form_top = QFormLayout()
        e_table_id = QLineEdit(self._suggest_table_id())
        form_top.addRow("Mã bảng:", e_table_id)
        e_name = QLineEdit()
        form_top.addRow("Tên bài test:", e_name)
        e_range = QLineEdit(sheet.used_range)
        form_top.addRow("Vùng dữ liệu (địa chỉ Excel, vd 'A2:W26'):", e_range)
        lay.addLayout(form_top)

        btn_reload = QPushButton("🔄 Đọc lại vùng này")
        lay.addWidget(btn_reload, alignment=Qt.AlignLeft)

        # `content`/`clay` được tạo CỐ ĐỊNH 1 LẦN DUY NHẤT ở đây — mỗi lần
        # "Đọc lại vùng này" chỉ dọn/dựng lại BÊN TRONG `clay` (xem
        # _clear_layout), KHÔNG bao giờ removeWidget()/insertWidget() trên
        # `lay` (layout NGOÀI) nữa. Lý do: Qt có lỗi hiếm gặp — remove rồi
        # insertWidget lại 1 widget khác vào ĐÚNG vị trí đó trên 1 layout đã
        # có sẵn item khác phía TRƯỚC (form_top/btn_reload ở đây) làm hỏng
        # phần vẽ (không phải dữ liệu) của các item phía trước đó: label
        # "Mã bảng:"/"Tên bài test:"/"Vùng dữ liệu..." và cả nút "🔄 Đọc lại
        # vùng này" biến mất khỏi màn hình (dù vẫn tồn tại, đọc lại đúng text
        # qua code) — đã tái hiện lỗi này trong 1 ví dụ Qt tối giản, tách
        # biệt hoàn toàn khỏi code của app.
        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(content)

        lay.addStretch()
        btn_continue = QPushButton("Tiếp tục →")
        btn_continue.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW}; font-weight:bold; padding:6px 14px;")
        lay.addWidget(btn_continue, alignment=Qt.AlignRight)

        state: dict = {}

        def _rebuild():
            range_str = e_range.text().strip()
            try:
                grid = xwio.read_range(self.xlsx_path, sheet.sheet_name, range_str)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Vùng không hợp lệ", f"Không đọc được vùng '{range_str}': {exc}")
                return

            _clear_layout(clay)

            n_rows = len(grid)
            n_cols = len(grid[0]) if grid else 0
            state["range_str"] = range_str
            state["grid"] = grid

            if any("report_val(" in c for row_texts in grid for c in row_texts):
                info = QLabel("✓ Vùng này đã có sẵn tag report_val() — những ô đó sẽ được NHẬN DIỆN "
                               "khi bấm Tiếp tục (xem chi tiết ở gợi ý dưới cột \"★ Giá trị đo\").")
                info.setWordWrap(True)
                info.setStyleSheet(f"color:{Colors.ACCENT_GREEN};")
                clay.addWidget(info)

            lbl_hint = QLabel(
                "Xem trước nội dung đọc được từ Excel (chỉ đọc, không sửa gì trong file) — dòng nào "
                "KHÔNG có sẵn tag report_val() trong (các) cột \"★ Giá trị đo\" tự động được coi là "
                "chữ tĩnh (vd dòng tiêu đề), KHÔNG tính là dòng dữ liệu:")
            lbl_hint.setWordWrap(True)
            clay.addWidget(lbl_hint)

            preview = QTableWidget(n_rows, n_cols)
            preview.setEditTriggers(QTableWidget.NoEditTriggers)
            preview.verticalHeader().setVisible(False)
            preview.setHorizontalHeaderLabels([f"Cột {c + 1}" for c in range(n_cols)])
            for r, row_texts in enumerate(grid):
                for c, text in enumerate(row_texts):
                    item = QTableWidgetItem(text)
                    if r == 0:
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    preview.setItem(r, c, item)
            preview.resizeColumnsToContents()
            preview.setMaximumHeight(220)
            clay.addWidget(preview)

            clay.addWidget(QLabel("Mỗi cột trong vùng trên nghĩa là gì? (dựa theo dòng tiêu đề):"))
            role_form = QFormLayout()
            role_combos = []
            header_texts = grid[0] if grid else []
            for c in range(n_cols):
                header_text = header_texts[c] if c < len(header_texts) else ""
                cb = _combo(wio.COLUMN_ROLE_CHOICES, current=wio.guess_column_role(header_text))
                role_form.addRow(f"Cột {c + 1} (\"{header_text}\"):", cb)
                role_combos.append(cb)
            clay.addLayout(role_form)

            state["role_combos"] = role_combos

        btn_reload.clicked.connect(_rebuild)
        _rebuild()

        btn_continue.clicked.connect(
            lambda _c=False, s=sheet, tid=e_table_id, nm=e_name, st=state: self._continue(s, tid, nm, st))

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidget(w)
        return scroller

    def _continue(self, sheet, e_table_id, e_name, state: dict):
        if "grid" not in state:
            QMessageBox.warning(self, "Lỗi", "Chưa đọc được vùng dữ liệu nào hợp lệ — kiểm tra lại 'Vùng dữ liệu'.")
            return
        table_id = e_table_id.text().strip()
        err = wio.validate_table_id_available(self.tables_dir, table_id)
        if err:
            QMessageBox.warning(self, "Lỗi", err)
            return
        name = e_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Lỗi", "Cần nhập Tên bài test.")
            return

        grid = state["grid"]
        role_combos = state["role_combos"]

        role_map = {i: cb.currentData() for i, cb in enumerate(role_combos)}
        measured_cols = sorted(i for i, r in role_map.items() if r == "measured")
        if not measured_cols:
            QMessageBox.warning(
                self, "Lỗi",
                "Phải chọn ÍT NHẤT 1 cột là '★ Giá trị đo (chỉ nhận diện ô đã có sẵn report_val())'.")
            return

        min_col, min_row, _max_col, _max_row = xwio.parse_range(state["range_str"])
        measured_cols_abs = [min_col + c for c in measured_cols]
        all_rows_abs = [min_row + i for i in range(len(grid))]

        # KHÔNG ghi gì vào file — chỉ ĐẾM số ô đã có sẵn ĐÚNG text
        # report_val('<table_id>') trong (các) cột "★ Giá trị đo" đã chọn,
        # CHO MỌI DÒNG trong vùng (xem docstring core/xlsx_wizard_io.py::
        # raw_counts_for_measured_cols). Dòng nào đếm được 0 -> TỰ ĐỘNG coi
        # là chữ tĩnh (vd dòng tiêu đề "lần 1"..."lần 5") và bỏ qua, không
        # cần khách khai báo dòng nào là tiêu đề.
        all_counts = xwio.raw_counts_for_measured_cols(
            self.xlsx_path, sheet.sheet_name, all_rows_abs, measured_cols_abs, table_id)
        skip_relative = frozenset(i for i, c in enumerate(all_counts) if c == 0)
        raw_counts = [c for c in all_counts if c > 0]

        rows = wio.build_rows_from_grid(grid, role_map, header_row_index=-1, extra_skip_rows=skip_relative)
        if not rows:
            QMessageBox.warning(
                self, "Chưa tìm thấy tag nào",
                f"Không tìm thấy ô nào đã có sẵn report_val('{table_id}') trong (các) cột \"★ Giá trị "
                f"đo\" đã chọn — không có dòng dữ liệu nào để nhận diện.\n\nHãy tự gõ tag "
                f"report_val('{table_id}') vào các ô dữ liệu tương ứng trong Excel rồi bấm "
                f"\"🔄 Đọc lại vùng này\".")
            return

        data_rows_abs = [r for i, r in enumerate(all_rows_abs) if i not in skip_relative]

        row_advanced = ({"value_format_seq": None}
                        if len(set(raw_counts)) == 1 and raw_counts and raw_counts[0] > 1
                        else None)

        spec = wio.WizardTableSpec(
            table_id=table_id, name=name, order=len(self.existing_descriptors) + 1,
            value_unit="", value_format="text", rows=rows,
            pass_rule={"type": "none"}, gcn=None,
        )
        tag_target = {
            "kind": "xlsx",
            "xlsx_path": self.xlsx_path, "sheet_name": sheet.sheet_name,
            "data_rows_abs": data_rows_abs, "measured_cols_abs": measured_cols_abs,
        }
        dlg = TableFormDialog(self.tables_dir, spec, is_new=True, tag_target=tag_target,
                               raw_counts=raw_counts, row_advanced=row_advanced,
                               xlsx_ref={"sheet": sheet.sheet_name, "range": state["range_str"]},
                               parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.imported_any = True
            self._sheets = xwio.list_sheets(self.xlsx_path)
            self._refresh_list()


def _pass_rule_summary(pass_rule: dict) -> str:
    key = pass_rule.get("type", "none")
    if key == "none":
        return "đánh dấu tay lúc chạy phiên (mặc định — không cần cấu hình gì)."
    for k, desc in wio.PASS_RULE_CHOICES:
        if k == key:
            return desc
    return "đánh dấu tay lúc chạy phiên (mặc định — không cần cấu hình gì)."


class PassRuleDialog(QDialog):
    """Cấu hình Quy tắc Đạt/Không đạt — TÁCH RIÊNG khỏi TableFormDialog
    (trước đây hiện luôn trên màn hình chính, khách phản hồi không hiểu các
    lựa chọn này để làm gì) — giờ chỉ hiện khi khách CHỦ ĐỘNG bấm "⚙ Bật so
    sánh tự động", mặc định bảng mới KHÔNG áp dụng công thức nào (kiểm định
    viên tự đánh dấu tay lúc chạy phiên, đã có sẵn cột Đạt/Không đạt ở Bước 2
    Phiên Kiểm Định)."""

    def __init__(self, current_pass_rule: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("So sánh Đạt/Không đạt tự động (nâng cao)")
        self.setMinimumSize(720, 420)
        lay = QVBoxLayout(self)

        hint = QLabel("Chỉ dùng nếu muốn phần mềm TỰ TÍNH Đạt/Không đạt từ công thức. "
                       "Không chọn gì thì kiểm định viên tự đánh dấu tay lúc chạy phiên.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        lay.addWidget(hint)

        self.pr_group = QButtonGroup(self)
        self.pr_widgets = {}
        current_pr = current_pass_rule.get("type", "none")
        for key, desc in wio.PASS_RULE_CHOICES:
            rb = QRadioButton(desc)
            rb.setProperty("pr_key", key)
            self.pr_group.addButton(rb)
            lay.addWidget(rb)
            # Chỉ "relative_error_vs_fixed_limit" cần nhập thêm tham số -> chỉ
            # dựng/hiện widget phụ cho đúng trường hợp đó, các lựa chọn khác
            # không có gì để nhập thì KHÔNG thêm widget rỗng vào layout (trước
            # đây vẫn thêm 1 QWidget rỗng rồi setVisible(True) khi chọn, hiện
            # ra thành 1 khoảng trống không rõ nghĩa gì).
            if key == "relative_error_vs_fixed_limit":
                extra = QWidget()
                extra_lay = QFormLayout(extra)
                params = current_pass_rule.get("params", {}) if current_pr == key else {}
                e_limit = QLineEdit(str(params.get("fixed_limit", "2.4e-7")))
                e_str = QLineEdit(params.get("limit_str", "± 2,4×10⁻⁷"))
                extra_lay.addRow("Ngưỡng sai số tương đối:", e_limit)
                extra_lay.addRow("Chuỗi hiển thị:", e_str)
                self.pr_widgets[key] = {"fixed_limit": e_limit, "limit_str": e_str, "extra": extra, "radio": rb}
                rb.setChecked(key == current_pr)
                rb.toggled.connect(lambda checked, ex=extra: ex.setVisible(checked))
                extra.setVisible(key == current_pr)
                lay.addWidget(extra)
            else:
                self.pr_widgets[key] = {"radio": rb}
                rb.setChecked(key == current_pr)
        if current_pr not in self.pr_widgets:
            self.pr_widgets["none"]["radio"].setChecked(True)

        lay.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.result_pass_rule = dict(current_pass_rule)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    def _on_save(self):
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
            self.result_pass_rule = {"type": pr_key, "params": {"fixed_limit": fixed_limit, "limit_str": limit_str}}
        else:
            self.result_pass_rule = {"type": pr_key}
        self.accept()


# =============================================================================
# 4) Form 1 bảng "đơn giản" — thêm mới HOẶC sửa lại
# =============================================================================

class TableFormDialog(QDialog):
    def __init__(self, tables_dir: Path, spec: "wio.WizardTableSpec", *,
                 is_new: bool = False, tag_target: dict | None = None,
                 raw_counts: list | None = None, row_advanced: dict | None = None,
                 row_value_format_seqs: list | None = None,
                 bienban_path: Path | None = None, xlsx_ref: dict | None = None, parent=None):
        """spec: WizardTableSpec ĐÃ DỰNG SẴN — sửa bảng có sẵn (is_new=False,
        wio.descriptor_to_spec(existing)) hoặc bảng MỚI đọc từ Word
        (is_new=True, ImportTableFromWordDialog dựng sẵn rows từ bảng Word
        thật). is_new=True cho phép đổi Mã bảng + bắt buộc kiểm tra mã chưa
        tồn tại trước khi lưu.

        tag_target: {"kind","docx_path"/"xlsx_path","table_index"/"sheet_name",
        "measured_cols"/"measured_cols_abs","header_row_index"/"data_rows_abs",...}
        — nếu có, ngay TRƯỚC KHI lưu sẽ ĐẾM LẠI số ô đã có sẵn tag
        report_val('<mã bảng>') trong chính file mẫu đó (xem
        core/table_wizard_io.py hoặc core/xlsx_wizard_io.py::
        raw_counts_for_measured_cols) — app KHÔNG tự ghi tag vào file, khách
        phải tự gõ tay trong Word/Excel trước.

        raw_counts: số report_val() CỦA TỪNG DÒNG (list, cùng độ dài
        spec.rows) — KHÔNG bắt buộc đồng nhất giữa các dòng: 1 dòng tổng hợp
        (vd "Trung Bình") có thể gộp nhiều ô "giá trị đo" hẹp thành 1 ô rộng
        nên chỉ cần ÍT report_val() hơn dòng đo thường (xem
        core/table_wizard_io.py::raw_counts_for_measured_cols — tự động suy
        ra từ cấu trúc ô THẬT trong Word, không cần khách tự gõ số này ở
        đâu cả). None = mọi dòng raw_count=1 (bảng đơn giản).

        row_advanced: {"value_format_seq": [...]} áp DÙNG CHUNG cho mọi dòng
        — CHỈ dùng được khi raw_counts đồng nhất (mọi dòng cùng 1 số) vì
        value_format_seq phải khớp ĐÚNG độ dài raw_count; khi raw_counts
        không đồng nhất, nút "⚙ Sửa cấu trúc report_val()" tự ẩn, mỗi dòng
        giữ nguyên value_format_seq riêng của nó (row_value_format_seqs,
        dùng khi sửa 1 bảng có sẵn — None = dòng đó dùng định dạng mặc định
        chung của bảng).

        bienban_path: đường dẫn bienban.docx/bienban.xlsx SỐNG của mẫu đang
        sửa — CHỈ dùng khi is_new=False (sửa bảng có sẵn) để quét lại file
        đó, tìm đúng vùng ô đã gắn tag report_val() của table_id này rồi
        hiện 1 bảng THAM KHẢO chỉ-xem (giống bảng rà soát Bước 2/3 —
        core/table_wizard_io.py::find_docx_table_grid /
        core/xlsx_wizard_io.py::find_xlsx_table_grid) — khách vừa sửa Khoá/
        Chuẩn/Ngưỡng vừa đối chiếu ngay cấu trúc thật, không cần mở Word/
        Excel song song. None hoặc không tìm thấy -> ẩn hẳn phần này, không
        báo lỗi (đúng tinh thần "chỉ hỗ trợ thêm", không chặn luồng sửa).

        xlsx_ref: {"sheet": str, "range": str} — vùng ô Excel THẬT khách đã
        chọn (ImportTableFromExcelDialog truyền vào khi vừa import, hoặc
        existing.xlsx_ref truyền lại khi sửa bảng có sẵn). Khi có, bảng THAM
        KHẢO ở trên đọc ĐÚNG vùng này (core/xlsx_wizard_io.py::read_range)
        thay vì tự dò/đoán lại bằng find_xlsx_table_grid() — khớp CHÍNH XÁC
        với vùng khách đã định nghĩa, không lệch theo quy tắc đoán chung.
        Luôn được GHI LẠI (giữ nguyên hoặc cập nhật) vào descriptor.xlsx_ref
        lúc Lưu, xem _do_save(). None với bảng dùng mẫu Word hoặc bảng Excel
        tạo trước khi có field này -> rơi về find_xlsx_table_grid như cũ."""
        super().__init__(parent)
        self.tables_dir = tables_dir
        self.is_new = is_new
        self.tag_target = tag_target
        self.row_advanced = row_advanced
        self._xlsx_ref = xlsx_ref
        raw_counts = list(raw_counts) if raw_counts is not None else [1] * len(spec.rows)
        row_value_format_seqs = row_value_format_seqs or [None] * len(spec.rows)

        self.setWindowTitle("Bảng mới — xác nhận trước khi lưu" if is_new else f"Sửa bảng {spec.table_id}")
        self.setMinimumSize(1500, 800)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        w = QWidget()
        lay = QVBoxLayout(w)

        form = QFormLayout()
        self.e_table_id = QLineEdit(spec.table_id)
        self.e_table_id.setEnabled(self.is_new)   # không đổi mã bảng khi sửa (tag docx đã cố định)
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
        self.chk_scientific = QCheckBox("Hiển thị dạng khoa học (×10ⁿ) — dùng cho sai số rất nhỏ")
        self.chk_scientific.setChecked(spec.value_format in ("sci", "sci_signed"))
        form.addRow("", self.chk_scientific)
        lay.addLayout(form)

        # Đa số bảng chỉ cần 1 trong 2 lựa chọn đơn giản ở trên (suy thẳng từ
        # Đơn vị, hoặc khoa học) — nhưng vài bảng cần đúng 1 trong 19 định
        # dạng đặc thù (vd "mv" có kèm đơn vị thay vì "mv_no_unit"). Checkbox
        # này thay cho cảnh báo cũ "sẽ bị đổi khi Lưu" — tự bật + chọn sẵn
        # đúng định dạng hiện có khi sửa 1 bảng đã dùng định dạng đặc thù, để
        # KHÔNG bị âm thầm đổi mất khi bấm Lưu.
        derivable_formats = set(wio._UNIT_TO_FORMAT_NO_UNIT.values()) | {"sci", "generic_no_unit"}
        needs_custom_format = not self.is_new and spec.value_format not in derivable_formats

        fmt_row = QHBoxLayout()
        self.chk_custom_format = QCheckBox("Dùng định dạng khác (nâng cao)")
        self.chk_custom_format.setChecked(needs_custom_format)
        fmt_row.addWidget(self.chk_custom_format)
        self.e_value_format_custom = _combo(wio.FORMAT_LABELS_ALL, current=spec.value_format)
        self.e_value_format_custom.setEnabled(needs_custom_format)
        fmt_row.addWidget(self.e_value_format_custom, 1)
        lay.addLayout(fmt_row)
        self.chk_custom_format.toggled.connect(self.e_value_format_custom.setEnabled)
        self.chk_custom_format.toggled.connect(self.chk_scientific.setDisabled)
        self.chk_scientific.setDisabled(needs_custom_format)

        if needs_custom_format:
            fmt_hint = QLabel(
                f"Bảng này đang dùng định dạng đặc thù ('{spec.value_format}') — đã tự bật + chọn "
                f"sẵn để KHÔNG bị đổi khi bạn Lưu. Bỏ tick nếu muốn quay về 2 lựa chọn đơn giản "
                f"(theo Đơn vị / khoa học) ở trên.")
            fmt_hint.setWordWrap(True)
            fmt_hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
            lay.addWidget(fmt_hint)

        # --- quy tắc đạt/không đạt — mặc định TẮT (đánh dấu tay lúc chạy
        # phiên), chỉ hiện ra khi khách chủ động bấm nút "nâng cao" ---
        self._pass_rule = dict(spec.pass_rule) if spec.pass_rule else {"type": "none"}
        pr_row = QHBoxLayout()
        self.lbl_pass_rule = QLabel(f"Đạt/Không đạt: {_pass_rule_summary(self._pass_rule)}")
        self.lbl_pass_rule.setWordWrap(True)
        pr_row.addWidget(self.lbl_pass_rule, 1)
        btn_pass_rule = QPushButton("⚙ So sánh tự động (nâng cao)")
        btn_pass_rule.clicked.connect(self._edit_pass_rule)
        pr_row.addWidget(btn_pass_rule)
        lay.addLayout(pr_row)

        # --- bảng THAM KHẢO chỉ-xem, dựng lại từ chính file mẫu SỐNG (xem
        # docstring bienban_path ở trên) — CHỈ hiện khi sửa bảng có sẵn VÀ
        # quét được đúng vùng ô của table_id này, im lặng bỏ qua nếu không
        # (mẫu chưa có file, chưa gắn tag, hoặc lỗi đọc file bất kỳ). ---
        if not self.is_new and bienban_path is not None:
            grid = None
            try:
                bienban_path = Path(bienban_path)
                if bienban_path.exists():
                    if bienban_path.suffix.lower() == ".xlsx":
                        # Ưu tiên đọc ĐÚNG vùng khách đã chọn lúc import
                        # (self._xlsx_ref) — chỉ rơi về dò/đoán lại
                        # (find_xlsx_table_grid) khi chưa có xlsx_ref (bảng
                        # cũ tạo trước khi có field này) hoặc đọc vùng đó
                        # lỗi (vd khách đã đổi tên sheet ngoài app).
                        if self._xlsx_ref:
                            try:
                                grid = xwio.read_range(
                                    bienban_path, self._xlsx_ref["sheet"], self._xlsx_ref["range"])
                            except Exception:  # noqa: BLE001
                                grid = None
                        if not grid:
                            grid = xwio.find_xlsx_table_grid(bienban_path, spec.table_id)
                    else:
                        grid = wio.find_docx_table_grid(bienban_path, spec.table_id)
            except Exception:  # noqa: BLE001
                grid = None
            if grid:
                btn_ref = QPushButton("▸ 📄 Cấu trúc thật trong file mẫu hiện tại (bấm để xem)")
                btn_ref.setCheckable(True)
                btn_ref.setStyleSheet("text-align:left; padding:4px 6px;")
                lay.addWidget(btn_ref)

                n_c = max((len(r) for r in grid), default=0)
                preview = QTableWidget(len(grid), n_c)
                preview.setEditTriggers(QTableWidget.NoEditTriggers)
                preview.verticalHeader().setVisible(False)
                preview.horizontalHeader().setVisible(False)
                for r, row_texts in enumerate(grid):
                    for c in range(n_c):
                        item = QTableWidgetItem(row_texts[c] if c < len(row_texts) else "")
                        if r == 0:
                            f = item.font()
                            f.setBold(True)
                            item.setFont(f)
                        preview.setItem(r, c, item)
                preview.resizeColumnsToContents()
                # KHÔNG dùng _fit_table_height() (ép sizePolicy Fixed + đúng
                # chiều cao TOÀN BỘ số dòng — bảng thật có thể vài chục dòng,
                # sẽ đè lên nội dung bên dưới) — chỉ giới hạn chiều cao tối đa,
                # dư thì tự có thanh cuộn RIÊNG bên trong bảng này.
                preview.setMaximumHeight(260)
                preview.setVisible(False)   # thu gọn mặc định — chỉ tham khảo, không chiếm chỗ form sửa
                lay.addWidget(preview)

                lbl_ref_hint = QLabel("Chỉ xem — muốn đổi bố cục/nhãn/công thức, sửa trực tiếp trong Word/Excel.")
                lbl_ref_hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
                lbl_ref_hint.setVisible(False)
                lay.addWidget(lbl_ref_hint)

                def _toggle_ref(checked, p=preview, h=lbl_ref_hint, b=btn_ref):
                    p.setVisible(checked)
                    h.setVisible(checked)
                    b.setText(("▾" if checked else "▸") +
                              " 📄 Cấu trúc thật trong file mẫu hiện tại (bấm để " +
                              ("ẩn" if checked else "xem") + ")")
                btn_ref.toggled.connect(_toggle_ref)

        # --- dữ liệu từng dòng — dựng TRƯỚC phần "cấu trúc report_val()" bên
        # dưới (dù hiện SAU trong layout) vì cần đọc raw_counts/
        # value_format_seq đã gắn theo từng dòng (Qt.UserRole) để tính tóm
        # tắt hiển thị. "Tần số thiết lập" (freq_set) KHÔNG hiện ở form đơn
        # giản này — chỉ dùng để hiển thị lại khi 1 cột docx tự gán role
        # "freq_set" (chưa có đường dẫn UI nào gán role đó qua form này),
        # không ảnh hưởng tới Đạt/Không đạt hay bảng rà soát Bước 2/3 (đọc
        # Khoá/Chuẩn dùng để tính/Ngưỡng) -> ẩn đi để đỡ rối cho người dùng
        # không rành kỹ thuật. Giữ nguyên None khi lưu; ai thực sự cần field
        # này sửa file JSON trực tiếp.
        n_rows = len(spec.rows)
        self.rows_table = QTableWidget(max(n_rows, 1), 4)
        self.rows_table.setHorizontalHeaderLabels(
            ["Khoá", "Chuẩn dùng để tính", "Ngưỡng", "Nhãn hiển thị"])
        # "Ngưỡng" (cột 2) LUÔN là cột nhìn thấy CUỐI CÙNG (cột 3 "Nhãn hiển
        # thị" ẩn vĩnh viễn ngay dưới đây) nên giãn đúng cột này — không dùng
        # setStretchLastSection() vì nó giãn theo CHỈ SỐ cuối cùng của MODEL
        # (cột 3), sẽ mất tác dụng khi cột đó đang ẩn.
        self.rows_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.rows_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rows_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # "Nhãn hiển thị" — khách phản hồi hiếm khi cần, ẨN VĨNH VIỄN cho MỌI
        # bảng để đỡ rối; dữ liệu cột này (nếu bảng cũ đã có) vẫn đọc/giữ
        # nguyên bình thường lúc Lưu (_do_save đọc thẳng qua self.rows_table.item,
        # không quan tâm cột có đang hiện hay không) — ai thực sự cần sửa
        # nhãn riêng thì sửa file JSON trực tiếp (display_label).
        self.rows_table.setColumnHidden(3, True)
        self._update_reference_column_visibility()
        for i, r in enumerate(spec.rows):
            key_item = QTableWidgetItem(r.key)
            # raw_count/value_format_seq CỦA ĐÚNG DÒNG NÀY — gắn qua
            # Qt.UserRole để tự đi theo dòng khi Thêm/Xoá dòng (KHÔNG hiện
            # ra ô nào cho khách gõ tay — đúng bài học từ TableDetailDialog
            # cũ: cho gõ tay "Số report_val()" tự do theo từng dòng từng
            # gây lệch dữ liệu giữa các dòng).
            key_item.setData(Qt.UserRole, raw_counts[i] if i < len(raw_counts) else 1)
            key_item.setData(Qt.UserRole + 1, row_value_format_seqs[i] if i < len(row_value_format_seqs) else None)
            self.rows_table.setItem(i, 0, key_item)
            self.rows_table.setItem(i, 1, QTableWidgetItem(
                "" if r.reference is None else _num_str(r.reference)))
            self.rows_table.setItem(i, 2, QTableWidgetItem(r.limit))
            self.rows_table.setItem(i, 3, QTableWidgetItem(r.display_label))
        self.rows_table.resizeColumnsToContents()

        # --- cấu trúc nhiều report_val()/dòng — CHỈ hiện khi có dòng nào
        # raw_count>1 (bảng có >1 cột "★ Giá trị đo" ở ImportTableFromWordDialog
        # hoặc dòng tổng hợp gộp ô); mặc định phương án đơn giản nhất, cùng
        # nguyên tắc "ẩn nâng cao" như pass_rule ở trên. Nút sửa định dạng
        # riêng CHỈ hiện khi mọi dòng CÙNG 1 số report_val() — value_format_seq
        # phải khớp đúng độ dài raw_count nên không áp dùng chung được khi
        # các dòng khác số nhau (vd dòng tổng hợp ít report_val() hơn). ---
        current_counts = self._current_raw_counts()
        if max(current_counts, default=1) > 1:
            uniform = len(set(current_counts)) == 1
            adv_row = QHBoxLayout()
            self.lbl_row_advanced = QLabel("")
            self.lbl_row_advanced.setWordWrap(True)
            self._refresh_row_advanced_summary()
            adv_row.addWidget(self.lbl_row_advanced, 1)
            if uniform:
                if self.row_advanced is None:
                    self.row_advanced = {"value_format_seq": None}
                btn_row_advanced = QPushButton("⚙ Sửa cấu trúc report_val() (nâng cao)")
                btn_row_advanced.clicked.connect(self._edit_row_advanced)
                adv_row.addWidget(btn_row_advanced)
            lay.addLayout(adv_row)

        lay.addWidget(QLabel("Dữ liệu từng dòng (điểm đo cố định của bảng — đúng số dòng "
                              "bạn đã gõ report_val() trong file .docx):"))

        def _add_row():
            row = self.rows_table.rowCount()
            self.rows_table.insertRow(row)
            key_item = QTableWidgetItem("")
            key_item.setData(Qt.UserRole, 1)
            key_item.setData(Qt.UserRole + 1, None)
            self.rows_table.setItem(row, 0, key_item)
            _fit_table_height(self.rows_table)

        def _del_row():
            rows = sorted({idx.row() for idx in self.rows_table.selectedIndexes()}, reverse=True)
            for row in rows:
                self.rows_table.removeRow(row)
            if rows:
                _fit_table_height(self.rows_table)

        row_btns = QHBoxLayout()
        btn_add_row = QPushButton("+ Thêm dòng")
        btn_add_row.clicked.connect(_add_row)
        row_btns.addWidget(btn_add_row)
        btn_del_row = QPushButton("− Xoá (các) dòng đang chọn")
        btn_del_row.clicked.connect(_del_row)
        row_btns.addWidget(btn_del_row)
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

    def _edit_pass_rule(self):
        dlg = PassRuleDialog(self._pass_rule, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._pass_rule = dlg.result_pass_rule
            self.lbl_pass_rule.setText(f"Đạt/Không đạt: {_pass_rule_summary(self._pass_rule)}")
            self._update_reference_column_visibility()

    def _update_reference_column_visibility(self):
        """"Chuẩn dùng để tính" chỉ THẬT SỰ cần khi quy tắc Đạt/Không đạt
        đang chọn dùng nó để tính (So sánh sai số tương đối/Tính số hiệu
        chỉnh) — ẩn ở mọi trường hợp khác (mặc định "Không áp dụng", hoặc
        "So sánh với ngưỡng") cho đỡ rối, đặc biệt bảng dùng mẫu Excel tự
        tính mọi công thức nên không cần cột này. CHỈ ẩn hiển thị — KHÔNG
        xoá dữ liệu, _do_save() vẫn đọc/ghi cột này bình thường dù đang ẩn,
        nên bảng nào đã có sẵn giá trị (vd Bảng A1 TEMPLATE_FREQ) không mất
        gì khi Lưu lại lúc cột đang ẩn."""
        needs_reference = self._pass_rule.get("type") in (
            "relative_error_vs_fixed_limit", "correction_vs_reference")
        self.rows_table.setColumnHidden(1, not needs_reference)

    def _current_raw_counts(self) -> list:
        """raw_count của TỪNG dòng đang hiện trong self.rows_table, đọc lại
        từ Qt.UserRole đã gắn (xem __init__/_add_row) — nguồn sự thật DUY
        NHẤT, không có biến self.raw_count/self.raw_counts riêng để tránh
        lệch dữ liệu khi Thêm/Xoá dòng."""
        counts = []
        for i in range(self.rows_table.rowCount()):
            item = self.rows_table.item(i, 0)
            counts.append((item.data(Qt.UserRole) if item else None) or 1)
        return counts

    def _refresh_row_advanced_summary(self):
        counts = self._current_raw_counts()
        if len(set(counts)) == 1:
            n = counts[0]
            fake_row = SimpleNamespace(raw_count=n, **(self.row_advanced or {"value_format_seq": None}))
            self.lbl_row_advanced.setText(f"Cấu trúc {n} report_val()/dòng: {_describe_row_structure(fake_row)}")
        else:
            self.lbl_row_advanced.setText(
                "Cấu trúc report_val()/dòng KHÔNG đồng đều giữa các dòng — tự động khớp đúng số ô "
                "\"giá trị đo\" THẬT mỗi dòng có trong Word (vd 1 dòng tổng hợp gộp nhiều ô hẹp "
                "thành 1 ô rộng thì chỉ cần ít report_val() hơn dòng đo thường): "
                + ", ".join(str(c) for c in counts) + ".")

    def _edit_row_advanced(self):
        table_id = self.e_table_id.text().strip() or self.e_table_id.text()
        n = self._current_raw_counts()[0]
        dlg = RowAdvancedDialog(f"mọi dòng của bảng {table_id}", n,
                                 self.row_advanced, default_format="text", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self.row_advanced = dlg.result_values()
            vfs = self.row_advanced.get("value_format_seq")
            for i in range(self.rows_table.rowCount()):
                item = self.rows_table.item(i, 0)
                if item:
                    item.setData(Qt.UserRole + 1, list(vfs) if vfs else None)
            self._refresh_row_advanced_summary()

    def _do_save(self):
        table_id = self.e_table_id.text().strip()
        if self.is_new:
            err = wio.validate_table_id_available(self.tables_dir, table_id)
            if err:
                QMessageBox.warning(self, "Lỗi", err)
                return
        name = self.e_name.text().strip()
        value_unit = self.e_value_unit.currentText().strip()
        if self.chk_custom_format.isChecked():
            value_format = self.e_value_format_custom.currentData() or "text"
        else:
            value_format = wio.resolve_value_format(value_unit, self.chk_scientific.isChecked())

        pass_rule = self._pass_rule
        pr_key = pass_rule.get("type", "none")

        # Nếu bảng gắn với 1 file mẫu thật (tag_target, Word HOẶC Excel) —
        # đếm lại NGAY TRƯỚC KHI lưu số ô ĐÃ CÓ SẴN tag report_val('<mã
        # bảng>') trong file (core/table_wizard_io.py hoặc core/
        # xlsx_wizard_io.py::raw_counts_for_measured_cols) — app KHÔNG ghi gì
        # vào file mẫu ở bước nào cả (Word lẫn Excel), dry-run này CHÍNH LÀ
        # kết quả cuối cùng. Không có tag_target (sửa bảng có sẵn, không
        # đụng file mẫu) -> giữ nguyên raw_count đã gắn theo từng dòng
        # (Qt.UserRole) từ lúc mở form.
        if self.tag_target:
            if self.tag_target.get("kind", "docx") == "xlsx":
                dry_run_counts = xwio.raw_counts_for_measured_cols(
                    self.tag_target["xlsx_path"], self.tag_target["sheet_name"],
                    self.tag_target["data_rows_abs"], self.tag_target["measured_cols_abs"], table_id)
            else:
                dry_run_counts = wio.raw_counts_for_measured_cols(
                    self.tag_target["docx_path"], self.tag_target["table_index"],
                    self.tag_target["measured_cols"], table_id,
                    self.tag_target.get("header_row_index", 0),
                    self.tag_target.get("extra_skip_rows", frozenset()))
        else:
            dry_run_counts = None
        ui_counts = self._current_raw_counts()

        rows = []
        for i in range(self.rows_table.rowCount()):
            def _cell(col):
                item = self.rows_table.item(i, col)
                return item.text().strip() if item else ""
            key = _cell(0)
            ref_text = _cell(1)
            reference = wio.guess_bare_number(ref_text) if ref_text else None
            if ref_text and reference is None:
                QMessageBox.warning(self, "Lỗi", f"Dòng {i + 1}: 'Chuẩn dùng để tính' phải là số.")
                return None
            rows.append(wio.WizardRowSpec(key=key, reference=reference,
                                           limit=_cell(2), display_label=_cell(3)))

        err = wio.validate_rows(rows, pass_rule)
        if err:
            QMessageBox.warning(self, "Lỗi", err)
            return

        spec = wio.WizardTableSpec(
            table_id=table_id, name=name, order=self.sp_order.value(),
            value_unit=value_unit, value_format=value_format,
            rows=rows, pass_rule=pass_rule, gcn=None,
        )
        raw_counts = dry_run_counts if dry_run_counts is not None else ui_counts
        # Số dòng dry-run (đúng cấu trúc Word thật) có thể khác số dòng đang
        # hiện trong form (khách tự Thêm/Xoá dòng tay) — khớp theo thứ tự,
        # dòng dư (nếu có) rơi về raw_count đã gắn sẵn trên UI (mặc định 1).
        while len(raw_counts) < len(rows):
            raw_counts = raw_counts + [ui_counts[len(raw_counts)] if len(raw_counts) < len(ui_counts) else 1]

        n_recognized = None
        try:
            if all(c == 1 for c in raw_counts):
                descriptor = wio.build_descriptor(spec)
            else:
                # Có dòng nào raw_count != 1 (0 — bảng Excel "chỉ nhận diện"
                # chưa thấy tag nào cho dòng đó, hoặc >1) — wio.build_descriptor()
                # ép cứng raw_count=1 cho MỌI dòng, không dùng được ở đây
                # (sẽ biến 0 thành 1 sai lệch); dựng RowDef/
                # TableDescriptor trực tiếp, MỖI DÒNG raw_count RIÊNG (không
                # bắt buộc đồng nhất). value_format_seq riêng từng dòng
                # (Qt.UserRole+1) — chỉ áp dụng nếu ĐÚNG độ dài raw_count của
                # dòng đó, sai độ dài thì rơi về định dạng mặc định của bảng
                # (an toàn, không lỗi validate_descriptor).
                row_defs = []
                for i, (r, count) in enumerate(zip(rows, raw_counts)):
                    item = self.rows_table.item(i, 0)
                    vfs = item.data(Qt.UserRole + 1) if item else None
                    if vfs is not None and len(vfs) != count:
                        vfs = None
                    row_defs.append(RowDef(
                        key=r.key, freq_set=r.freq_set, reference=r.reference,
                        raw_count=count, limit=r.limit, display_label=r.display_label,
                        value_format_seq=list(vfs) if vfs else None))
                descriptor = TableDescriptor(
                    schema_version=1, table_id=table_id, name=name, order=self.sp_order.value(),
                    scenario_file="", layout="repeated_rows", value_unit=value_unit,
                    value_format=value_format, rows=row_defs, columns=[],
                    pass_rule=pass_rule, merge=[], gcn=None,
                )
                errs = validate_descriptor(descriptor)
                if errs:
                    QMessageBox.warning(self, "Dữ liệu chưa hợp lệ", "\n".join(errs))
                    return
            # Giữ nguyên/gán vùng ô Excel THẬT đã chọn (self._xlsx_ref — từ
            # ImportTableFromExcelDialog nếu vừa import, hoặc từ descriptor
            # cũ nếu đang sửa) để lần sau mở "Sửa bảng" hiện lại ĐÚNG vùng
            # đó, không phải tự dò/đoán (xem docstring bienban_path/xlsx_ref
            # ở __init__). wio.build_descriptor()/TableDescriptor(...) ở
            # trên không biết field này nên phải gán tay sau khi dựng xong.
            descriptor.xlsx_ref = self._xlsx_ref
            timport.apply_table_to_existing(self.tables_dir, descriptor)
            if self.tag_target:
                # KHÔNG ghi gì vào file mẫu (Word lẫn Excel) — dry_run_counts
                # ở trên ĐÃ LÀ số ô nhận diện được (đã có sẵn tag report_val()
                # do khách tự gõ tay), dùng lại luôn để báo cho khách biết.
                n_recognized = sum(dry_run_counts)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi khi lưu", str(exc))
            return
        if n_recognized is not None:
            file_kind = "Excel" if self.tag_target.get("kind", "docx") == "xlsx" else "Word"
            QMessageBox.information(
                self, "Đã lưu",
                f"Đã lưu bảng '{table_id}' — nhận diện được {n_recognized} ô đã có sẵn report_val() "
                f"trong file {file_kind}. Dòng nào chưa có tag sẽ chưa nhận dữ liệu (raw_count=0) — "
                f"tự gõ tag report_val('{table_id}') vào file rồi Sửa bảng lại nếu cần.")
        self.accept()


def _num_str(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return str(v)
