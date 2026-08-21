"""
gui/report_preview.py
======================
Dựng QTableWidget cho khung xem trước/rà soát kết quả — dùng ở cả Bước 2
(rà soát + xác nhận từng dòng, có cột checkbox) và Bước 3 (xem trước báo
cáo, không có checkbox).

Nhiệm vụ QUAN TRỌNG NHẤT của khung này (đặc biệt Bước 2) là cho kiểm định
viên xác nhận report_val() kịch bản đẩy có đang rơi ĐÚNG vị trí/thứ tự cột
thật trong bienban.docx hay không — TRƯỚC KHI tính tới việc tự tính Đạt/
Không đạt (nếu bảng có pass_rule) hay để kiểm định viên tự chọn tay (nếu
không tính được, hoặc cần chọn value cụ thể xuất ra GCN qua right-click).
Vì vậy build_wysiwyg_table() ưu tiên đọc TRỰC TIẾP cấu trúc cột từ chính
file bienban.docx thật (_build_from_docx_grid, qua core/table_wizard_io.py::
find_docx_table_grid/value_columns_from_grid) — tiêu đề cột lấy nguyên văn
từ dòng tiêu đề thật (vd "lần 1"/"Độ KĐBĐ"), không phải tên chung "Lần N".
Chỉ khi KHÔNG tìm được bảng thật khớp (mẫu mới chưa có docx, bảng chưa gắn
tag) mới rơi về _build_generic (tên cột chung chung, không khớp docx thật).
_TEMPLATE_BUILDERS giữ lại làm điểm mở rộng nếu 1 template thật sự cần lưới
tuỳ biến tay riêng (ưu tiên cao nhất, kiểm tra trước cả 2 đường trên).
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox, QComboBox, QLabel, QWidget, QHBoxLayout, QInputDialog, QMenu,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from core.session import TableRow
from core.report_generator import _fmt_freq, _fmt_dbm
from core.report_generator_nrp2 import _power_set_from_key
from core import table_layouts as _lay
from core import table_wizard_io as wio
from core.report_templates import get_template
from gui.widgets import CheckBoxHeader
from gui.theme import Colors


def _new_table(n_rows: int, headers: list[str]) -> QTableWidget:
    tbl = QTableWidget(n_rows, len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return tbl


def _set_cell(tbl: QTableWidget, row: int, col: int, text: str):
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignCenter)
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    tbl.setItem(row, col, it)


def _empty_table(message: str) -> QTableWidget:
    tbl = _new_table(1, ["Ghi chú"])
    _set_cell(tbl, 0, 0, message)
    return tbl


# ---------------------------------------------------------------------------
# Sửa tay giá trị đo đã bind — double-click 1 ô "giá trị đo" (khi bài đã có
# kết quả thật) mở dialog nhập số mới, tính lại error/passed rồi báo cho
# caller dựng lại bảng qua on_value_edited (Bước 2/Bước 3 đã có sẵn cơ chế
# refresh, xem gui/session_manager.py). Dùng bởi 1 builder tuỳ biến tương
# lai nếu cần (hiện không có builder nào đăng ký).
# ---------------------------------------------------------------------------

def _make_editable(tbl: QTableWidget, row: int, col: int, get_current, apply_edit, on_value_edited):
    """Đánh dấu ô (row,col) — vốn đã có QTableWidgetItem — có thể double-click
    để sửa. get_current() trả giá trị SỐ hiện tại (không phải chuỗi đã định
    dạng) để prefill dialog; apply_edit(new_value) ghi giá trị mới + tính lại
    các field liên quan trên TableRow.

    Đăng ký theo id(item) chứ KHÔNG theo (row,col): _add_checkbox_column gọi
    insertColumn(0) SAU khi các ô này đã được đăng ký — Qt tự dịch ITEM sang
    phải 1 cột nhưng không báo lại toạ độ mới cho dict tra cứu nếu dùng
    (row,col) làm khoá, khiến double-click ở vị trí thật không khớp khoá cũ.
    Tra theo item — vẫn đúng vị trí THẬT vì item vẫn là chính nó sau khi dịch."""
    it = tbl.item(row, col)
    if it is None:
        return
    it.setToolTip("Double-click để sửa giá trị đo")
    if not hasattr(tbl, "_editable_items"):
        tbl._editable_items = {}
        tbl.cellDoubleClicked.connect(lambda r, c: _handle_value_dblclick(tbl, r, c))
    tbl._editable_items[id(it)] = (get_current, apply_edit, on_value_edited)


def _handle_value_dblclick(tbl: QTableWidget, row: int, col: int):
    it = tbl.item(row, col)
    if it is None:
        return
    entry = getattr(tbl, "_editable_items", {}).get(id(it))
    if entry is None:
        return
    get_current, apply_edit, on_value_edited = entry
    current = get_current()
    new_value, ok = QInputDialog.getDouble(
        tbl, "Sửa giá trị đo", "Nhập giá trị mới:",
        float(current) if current is not None else 0.0,
        -1e15, 1e15, 6)
    if not ok:
        return
    apply_edit(new_value)
    if on_value_edited:
        on_value_edited()


def _tint_edited(tbl: QTableWidget, cells: list, edited: bool):
    """Tô nền các ô thuộc 1 dòng đã bị sửa tay (TableRow.edited=True) — dùng
    màu ACCENT_MAGENTA giống cách đánh dấu bước report_val trong Scenario
    Builder, nhất quán ý nghĩa "có bàn tay người can thiệp vào đây"."""
    if not edited:
        return
    for row, col in cells:
        it = tbl.item(row, col)
        if it is None:
            continue
        it.setBackground(QColor(Colors.ACCENT_MAGENTA))
        it.setForeground(QColor(Colors.BG_WINDOW))
        tip = it.toolTip()
        it.setToolTip((tip + "\n" if tip else "") + "Dòng này có giá trị đã sửa tay")


def _set_gcn_export_mark(all_rows: list, row_obj: TableRow, field_key: str) -> None:
    """Đặt field_key làm giá trị xuất GCN cho row_obj, xoá mark ở MỌI dòng
    khác trong bảng — bất biến "chỉ đúng 1 dòng/bảng được đánh dấu tại 1
    thời điểm" (xem TableRow.gcn_export_field)."""
    for r in all_rows:
        r.gcn_export_field = field_key if r is row_obj else None


def _tint_gcn_marked(tbl: QTableWidget, cells: list):
    for row, col in cells:
        it = tbl.item(row, col)
        if it is None:
            continue
        it.setBackground(QColor(Colors.ACCENT_RED))
        it.setForeground(QColor(Colors.BG_WINDOW))
        tip = it.toolTip()
        it.setToolTip((tip + "\n" if tip else "") +
                      "Ô này đang được đánh dấu 'Xuất value trong GCN'")


def _handle_gcn_context_menu(tbl: QTableWidget, pos):
    it = tbl.itemAt(pos)
    if it is None:
        return
    entry = getattr(tbl, "_gcn_markable_items", {}).get(id(it))
    if entry is None:
        return
    all_rows, row_obj, field_key, on_mark_changed = entry
    is_marked = row_obj.gcn_export_field == field_key
    menu = QMenu(tbl)
    action = menu.addAction("Bỏ đánh dấu xuất GCN" if is_marked else "Đánh dấu xuất GCN")
    chosen = menu.exec_(tbl.viewport().mapToGlobal(pos))
    if chosen is not action:
        return
    if is_marked:
        row_obj.gcn_export_field = None
    else:
        _set_gcn_export_mark(all_rows, row_obj, field_key)
    if on_mark_changed:
        on_mark_changed()


def _make_gcn_markable(tbl: QTableWidget, row: int, col: int, all_rows: list,
                       row_obj: TableRow, field_key: str, on_mark_changed=None):
    """Đăng ký ô (row,col) — 1 giá trị đo (report_val) — click phải để
    đánh dấu/bỏ đánh dấu "Xuất value trong GCN" cho DÒNG chứa ô này (thấy ở
    cột readonly cùng tên, xem _add_gcn_export_column). Chỉ ĐÚNG 1 dòng
    trong CẢ BẢNG được đánh dấu tại 1 thời điểm — đánh dấu 1 ô sẽ tự bỏ
    đánh dấu ở dòng khác (kể cả ô khác trong CÙNG dòng, do field_key đổi).
    Đăng ký theo id(item) — cùng lý do với _make_editable (insertColumn(0)
    của _add_checkbox_column dịch item sang phải, tra theo (row,col) sẽ sai)."""
    it = tbl.item(row, col)
    if it is None:
        return
    if not hasattr(tbl, "_gcn_markable_items"):
        tbl._gcn_markable_items = {}
        tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        tbl.customContextMenuRequested.connect(lambda pos: _handle_gcn_context_menu(tbl, pos))
    tbl._gcn_markable_items[id(it)] = (all_rows, row_obj, field_key, on_mark_changed)
    if row_obj.gcn_export_field == field_key:
        _tint_gcn_marked(tbl, [(row, col)])


def _finish(tbl: QTableWidget) -> QTableWidget:
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return tbl


def _add_checkbox_column(tbl: QTableWidget, row_groups: list, on_toggle=None, enabled: bool = True):
    """Chèn cột 'Đưa vào báo cáo' ở đầu bảng — Qt tự dịch cell/span có sẵn
    sang phải khi insertColumn(0). row_groups: [(start_row, end_row_excl,
    TableRow), ...] — 1 nhóm có thể trải nhiều dòng lưới (vd bảng đo lặp N
    lần chỉ có 1 TableRow nhưng N dòng hiển thị từng lần đo). enabled=False
    hiện checkbox nhưng khoá (bài chưa có kết quả thật để xác nhận) — khi đó
    không gắn checkbox "chọn tất cả" ở header (không có gì để chọn)."""
    tbl.insertColumn(0)
    checks: list[QCheckBox] = []
    header = None
    if enabled:
        header = CheckBoxHeader(tbl, label="")
        header.setToolTip("Tick để chọn/bỏ chọn TẤT CẢ vào báo cáo")
        tbl.setHorizontalHeader(header)
    tbl.setHorizontalHeaderItem(0, QTableWidgetItem("Đưa vào\nbáo cáo"))

    def _update_header():
        if header:
            header.setChecked(bool(checks) and all(c.isChecked() for c in checks))

    for start, end, r in row_groups:
        chk = QCheckBox()
        chk.setChecked(r.confirmed)
        chk.setEnabled(enabled)
        checks.append(chk)

        def _make_cb(row_obj, checkbox):
            def _cb(_state):
                row_obj.confirmed = checkbox.isChecked()
                _update_header()
                if on_toggle:
                    on_toggle()
            return _cb

        chk.stateChanged.connect(_make_cb(r, chk))
        cell_w = QWidget()
        lay = QHBoxLayout(cell_w)
        lay.addWidget(chk)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(4, 0, 4, 0)
        tbl.setCellWidget(start, 0, cell_w)
        if end - start > 1:
            tbl.setSpan(start, 0, end - start, 1)

    if header:
        def _toggle_all(checked):
            for c in checks:
                c.setChecked(checked)
        header.toggled_all.connect(_toggle_all)
        _update_header()

    tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    tbl.setColumnWidth(0, 70)


_STATUS_OPTIONS = [("—", None), ("✅ Đạt", True), ("❌ Không đạt", False)]
_STATUS_INDEX = {None: 0, True: 1, False: 2}


def _add_status_column(tbl: QTableWidget, row_groups: list, on_change=None, enabled: bool = True):
    """Thêm cột 'Đạt/Không đạt' ở CUỐI bảng — combobox cho kiểm định viên tự
    chọn/ghi đè TableRow.passed (chỉ hỗ trợ rà soát trong app, KHÔNG in vào
    file docx xuất ra). Cùng cấu trúc row_groups như _add_checkbox_column.
    enabled=False hiện combobox nhưng khoá (bài chưa có kết quả thật)."""
    col = tbl.columnCount()
    tbl.setColumnCount(col + 1)
    tbl.setHorizontalHeaderItem(col, QTableWidgetItem("Đạt/\nKhông đạt"))
    for start, end, r in row_groups:
        combo = QComboBox()
        for label, _ in _STATUS_OPTIONS:
            combo.addItem(label)
        combo.setCurrentIndex(_STATUS_INDEX.get(r.passed, 0))
        combo.setEnabled(enabled)

        def _make_cb(row_obj):
            def _cb(index):
                row_obj.passed = _STATUS_OPTIONS[index][1]
                if on_change:
                    on_change()
            return _cb

        combo.currentIndexChanged.connect(_make_cb(r))
        tbl.setCellWidget(start, col, combo)
        if end - start > 1:
            tbl.setSpan(start, col, end - start, 1)


_GCN_MARK_ON = "●"
_GCN_MARK_OFF = "○"


def _add_gcn_export_column(tbl: QTableWidget, row_groups: list):
    """Thêm cột 'Xuất value trong GCN' ở CUỐI bảng, NGAY SAU cột Đạt/Không
    đạt — chỉ đọc, phản ánh TableRow.gcn_export_field (đặt qua click phải 1
    ô giá trị đo, xem _make_gcn_markable). Rỗng ở MỌI dòng (mặc định) = GCN
    theo Đạt/Không đạt như cũ; đúng 1 dòng có gcn_export_field != None = GCN
    xuất giá trị của dòng đó thay vì Đạt/Không đạt (core/table_engine.py::
    _gcn_export_value_str).

    Dùng QLabel + glyph chấm tròn (●/○) thay vì QRadioButton::indicator —
    style QSS tuỳ biến cho ::indicator bị Qt clip/méo hình khi cột hẹp (đã
    thực nghiệm thấy vỡ hình), QLabel tránh hẳn rủi ro đó vì chỉ vẽ 1 ký tự
    theo font, không có box-model indicator phức tạp."""
    col = tbl.columnCount()
    tbl.setColumnCount(col + 1)
    tbl.setHorizontalHeaderItem(col, QTableWidgetItem("Xuất value\ntrong GCN"))
    for start, end, r in row_groups:
        marked = r.gcn_export_field is not None
        lbl = QLabel(_GCN_MARK_ON if marked else _GCN_MARK_OFF)
        color = Colors.ACCENT_PRIMARY if marked else Colors.TEXT_DIM
        lbl.setStyleSheet(f"font-size:15px; color:{color}; background:transparent;")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setToolTip(
            "Chỉ đọc — tự bật khi có 1 ô giá trị đo trong dòng này được click "
            "phải rồi chọn 'Đánh dấu xuất GCN'. Tắt ở mọi dòng = GCN xuất "
            "Đạt/Không đạt như bình thường.")
        cell_w = QWidget()
        lay = QHBoxLayout(cell_w)
        lay.addWidget(lbl)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(4, 0, 4, 0)
        tbl.setCellWidget(start, col, cell_w)
        if end - start > 1:
            tbl.setSpan(start, col, end - start, 1)


# ---------------------------------------------------------------------------
# Bảng RÀ SOÁT CHUNG — dùng cho MỌI template không có builder riêng khớp
# pixel với layout docx thật (tức MỌI template hiện nay — data-driven qua
# core/report_templates/generic.py, không có class Python riêng). Không cố
# khớp đúng cột như file docx xuất ra — chỉ cho kiểm định viên THẤY ĐƯỢC
# đúng những giá trị report_val() kịch bản đã đẩy cho từng dòng để rà soát
# trước khi tick xác nhận, thay vì màn hình trống "Không rõ định dạng bảng".
# ---------------------------------------------------------------------------

def _fmt_num(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        v = int(v)
    return str(v).replace(".", ",")


def _edit_raw_reading(recompute_row, r: TableRow, row_index: int, reading_index: int, on_value_edited):
    """Sửa tay ĐÚNG 1 lần đo (report_val[reading_index]) trong dòng r — dùng
    khi dòng có >1 lần đo (vd A1 công suất: 10 cột). recompute_row(row_index,
    raw_readings) tính lại measured/error/limit/passed từ ĐÚNG công thức
    pass_rule của bảng, khớp với lúc map_table() tính ban đầu."""
    def get_current():
        return r.raw_readings[reading_index]

    def apply_edit(new_value):
        r.raw_readings[reading_index] = new_value
        result = recompute_row(row_index, r.raw_readings)
        if result is not None:
            r.value_measured, r.error, r.limit, r.passed = result
        r.edited = True

    return get_current, apply_edit, on_value_edited


def _edit_single_value(recompute_row, r: TableRow, row_index: int, on_value_edited):
    """Sửa tay khi dòng chỉ có 1 lần đo (cột 'Giá trị report_val() đã đẩy')."""
    def get_current():
        return r.raw_readings[0] if r.raw_readings else r.value_measured

    def apply_edit(new_value):
        if r.raw_readings:
            r.raw_readings[0] = new_value
        else:
            r.raw_readings = [new_value]
        result = recompute_row(row_index, r.raw_readings)
        if result is not None:
            r.value_measured, r.error, r.limit, r.passed = result
        r.edited = True

    return get_current, apply_edit, on_value_edited


def _build_generic(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                   with_status: bool = False, on_status_change=None,
                   interactive: bool = True, on_value_edited=None,
                   recompute_row=None, measured_counts: list | None = None) -> QTableWidget:
    # FALLBACK khi không tìm được bảng thật khớp trong bienban.docx (xem
    # _build_from_docx_grid — luôn được ưu tiên trước nếu tìm thấy) — KHÔNG
    # đọc cấu trúc/tên cột từ file docx thật, chỉ tách mỗi report_val()
    # thành 1 cột riêng để dễ rà soát. Tên cột generic "Lần N" — riêng với
    # dòng có measured_counts (report_val() ĐẦU dùng cho công thức, các
    # slot SAU do kịch bản TỰ TÍNH rồi đẩy thêm, xem core/table_engine.py::
    # apply_pass_rule), các slot SAU đổi tên "KB tính N" để phân biệt rõ với
    # lần đo thật.
    #
    # KHÔNG có cột "Trung bình" — bỏ hẳn (từng có nhưng gây hiểu lầm: kể từ
    # khi phần mềm ngừng tự tính trung bình, giá trị cột đó luôn trùng y hệt
    # "Lần 1", không còn là trung bình gì cả).
    max_readings = max((len(r.raw_readings) for r in rows), default=0)
    show_error = any(r.error is not None for r in rows)
    show_limit = any((r.limit or "").strip() for r in rows)

    mc = None
    if measured_counts:
        mc = next((c for c in measured_counts if c is not None), None)

    if max_readings > 1:
        if mc is not None and mc < max_readings:
            value_headers = [f"Lần {j + 1}" if j < mc else f"KB tính {j - mc + 1}"
                             for j in range(max_readings)]
        else:
            value_headers = [f"Lần {j + 1}" for j in range(max_readings)]
    else:
        value_headers = ["Giá trị report_val() đã đẩy"]

    headers = ["Khoá", *value_headers]
    if show_error:
        headers.append("Sai số")
    if show_limit:
        headers.append("Ngưỡng")

    tbl = _new_table(len(rows), headers)
    for i, r in enumerate(rows):
        col = 0
        _set_cell(tbl, i, col, r.key)
        col += 1

        unit = f" {r.value_unit}" if r.value_unit else ""
        value_cols = []
        if r.raw_readings:
            for j in range(max_readings):
                text = _fmt_num(r.raw_readings[j]) + unit if j < len(r.raw_readings) else ""
                _set_cell(tbl, i, col, text)
                if j < len(r.raw_readings) and interactive and recompute_row:
                    _make_editable(tbl, i, col,
                                   *_edit_raw_reading(recompute_row, r, i, j, on_value_edited))
                if j < len(r.raw_readings):
                    _make_gcn_markable(tbl, i, col, rows, r, f"raw:{j}", on_value_edited)
                value_cols.append(col)
                col += 1
        else:
            single_text = (_fmt_num(r.value_measured) + unit) if r.value_measured is not None else ""
            _set_cell(tbl, i, col, single_text)
            if r.value_measured is not None and interactive and recompute_row:
                _make_editable(tbl, i, col,
                               *_edit_single_value(recompute_row, r, i, on_value_edited))
            value_cols.append(col)
            col += 1
            for _ in range(max_readings - 1):
                _set_cell(tbl, i, col, "")
                col += 1

        if show_error:
            _set_cell(tbl, i, col, _fmt_num(r.error) if r.error is not None else "")
            col += 1
        if show_limit:
            _set_cell(tbl, i, col, r.limit or "")
            col += 1

        if r.edited:
            _tint_edited(tbl, [(i, c) for c in value_cols], True)

    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
        _add_gcn_export_column(tbl, row_groups)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


# ---------------------------------------------------------------------------
# Builder đọc TRỰC TIẾP cấu trúc cột từ chính file bienban.docx thật (qua
# core/table_wizard_io.py::find_docx_table_grid/value_columns_from_grid) —
# nhiệm vụ QUAN TRỌNG NHẤT của Bước 2 là cho kiểm định viên xác nhận được
# report_val() kịch bản đẩy có đang rơi ĐÚNG vị trí/thứ tự cột thật trong
# Word hay không, TRƯỚC KHI tính tới việc tự tính Đạt/Không đạt hay chọn tay
# — nên tiêu đề cột ở đây LUÔN lấy nguyên văn từ dòng tiêu đề thật trong
# docx (vd "lần 1"/"Độ KĐBĐ"), không phải tên chung "Lần N" như _build_generic.
# Áp dụng cho MỌI template (data-driven, không cần đăng ký builder tay như
# _TEMPLATE_BUILDERS bên dưới) — chỉ cần bảng đã gắn tag report_val() trong
# bienban.docx. Rơi về _build_generic nếu chưa tìm được bảng thật khớp (mẫu
# mới chưa có docx, table_id gõ sai, hoặc bảng chưa gắn tag nào).
# ---------------------------------------------------------------------------

def _build_from_docx_grid(rows: list[TableRow], grid: list, value_cols: list, header_row: int = 0,
                          with_checkbox: bool = False, on_toggle=None,
                          with_status: bool = False, on_status_change=None,
                          interactive: bool = True, on_value_edited=None,
                          recompute_row=None, measured_counts: list | None = None) -> QTableWidget:
    header_texts = grid[header_row] if header_row < len(grid) else []
    value_headers = [header_texts[c] if c < len(header_texts) else f"Cột {c + 1}" for c in value_cols]

    show_error = any(r.error is not None for r in rows)
    show_limit = any((r.limit or "").strip() for r in rows)

    headers = ["Khoá", *value_headers]
    if show_error:
        headers.append("Sai số")
    if show_limit:
        headers.append("Ngưỡng")

    tbl = _new_table(len(rows), headers)
    for i, r in enumerate(rows):
        col = 0
        _set_cell(tbl, i, col, r.key)
        col += 1

        unit = f" {r.value_unit}" if r.value_unit else ""
        value_cell_cols = _fill_value_slots(
            tbl, i, col, r, i, 0, len(value_cols), unit=unit,
            interactive=interactive, recompute_row=recompute_row,
            on_value_edited=on_value_edited, all_rows=rows)
        col += len(value_cols)

        if show_error:
            _set_cell(tbl, i, col, _fmt_num(r.error) if r.error is not None else "")
            col += 1
        if show_limit:
            _set_cell(tbl, i, col, r.limit or "")
            col += 1

        if r.edited:
            _tint_edited(tbl, [(i, c) for c in value_cell_cols], True)

    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
        _add_gcn_export_column(tbl, row_groups)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


def _docx_grid_for(template_id: str, table_id: str):
    """(grid, value_cols) đọc trực tiếp từ bienban.docx thật của template —
    None nếu không tìm được (lỗi bất kỳ khi đọc, template/bảng không tồn
    tại, file chưa có, hoặc bảng chưa gắn tag report_val() nào) -> caller
    rơi về _build_generic thay vì crash."""
    try:
        tpl = get_template(template_id)
        docx_path = getattr(tpl, "bienban_docx_path", None)
        if docx_path is None:
            return None
        grid = wio.find_docx_table_grid(docx_path, table_id)
        if grid is None:
            return None
        value_cols = wio.value_columns_from_grid(grid)
        if not value_cols:
            return None
        return grid, value_cols
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Builder RIÊNG khớp ĐÚNG layout file docx thật — TEMPLATE_FREQ (8 bảng) +
# TEMPLATE_POWER (3 bảng). Tiêu đề cột lấy từ core/table_layouts.py — CÙNG
# nguồn scripts/build_generic_seed_templates.py dùng để dựng file .docx thật,
# đảm bảo Bước 2/Bước 3 hiển thị KHỚP HỆT cấu trúc file khách hàng đã cung
# cấp (không phải bảng rà soát chung nữa) theo đúng yêu cầu đã chốt.
# ---------------------------------------------------------------------------

def _merge_whole_widget(tbl: QTableWidget, col: int, start_row: int, n: int, text: str):
    _set_cell(tbl, start_row, col, text)
    if n > 1:
        tbl.setSpan(start_row, col, n, 1)


def _merge_consecutive_widget(tbl: QTableWidget, col: int, start_row: int, n: int, values: list):
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[j + 1] == values[i]:
            j += 1
        _set_cell(tbl, start_row + i, col, values[i])
        if j > i:
            tbl.setSpan(start_row + i, col, j - i + 1, 1)
        i = j + 1


def _fill_value_slots(tbl: QTableWidget, row: int, col_start: int, r: TableRow, row_index: int,
                      start_idx: int, count: int, unit: str = "",
                      interactive: bool = True, recompute_row=None, on_value_edited=None,
                      all_rows: list | None = None) -> list:
    """Điền `count` ô liên tiếp từ (row, col_start) bằng
    r.raw_readings[start_idx : start_idx+count] — đúng thứ tự report_val()
    kịch bản đã đẩy. Bật sửa tay (double-click) nếu interactive+recompute_row.
    all_rows (nếu có) bật thêm click-phải "Đánh dấu xuất GCN" cho từng ô
    (xem _make_gcn_markable) — field_key = "raw:<idx>" khớp đúng chỉ số
    raw_readings mà core/table_engine.py::_gcn_export_value_str đọc lại.
    Trả về list toạ độ cột đã điền (tô màu 'đã sửa')."""
    cols = []
    for k in range(count):
        idx = start_idx + k
        col = col_start + k
        text = (_fmt_num(r.raw_readings[idx]) + unit) if idx < len(r.raw_readings) else ""
        _set_cell(tbl, row, col, text)
        if idx < len(r.raw_readings) and interactive and recompute_row:
            _make_editable(tbl, row, col,
                           *_edit_raw_reading(recompute_row, r, row_index, idx, on_value_edited))
        if idx < len(r.raw_readings) and all_rows is not None:
            _make_gcn_markable(tbl, row, col, all_rows, r, f"raw:{idx}", on_value_edited)
        cols.append(col)
    return cols


def _finish_rows(tbl: QTableWidget, row_groups: list, with_checkbox: bool, on_toggle,
                 with_status: bool, on_status_change, interactive: bool,
                 tint: list) -> QTableWidget:
    for i, cols in tint:
        _tint_edited(tbl, [(i, c) for c in cols], True)
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
        _add_gcn_export_column(tbl, row_groups)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


def _build_freq_a1(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                   interactive=True, on_value_edited=None, recompute_row=None,
                   measured_counts=None) -> QTableWidget:
    """Khớp ĐÚNG cấu trúc dựng trong scripts/build_generic_seed_templates.py
    (nhánh 'if tid == "A1"'): cột 0 (Tần số thiết lập) gộp dọc CẢ n+1 dòng;
    cột 1 (fCi) mỗi dòng 1 lần đo RIÊNG (dọc, không phải ngang); fC/δf/Sai
    số cho phép CHỈ nằm ở DÒNG CUỐI (không gộp, không lặp lại các dòng
    trên) — vì docx đặt fC/δf ở 1 dòng riêng sau khối fCi (tránh lỗi thứ tự
    report_val() đã thực nghiệm bắt được khi gộp dọc xuyên khối fCi)."""
    r = rows[0]
    n = (measured_counts[0] if measured_counts and measured_counts[0] is not None
         else len(r.raw_readings))
    tbl = _new_table(n + 1, _lay.FREQ_A1_HEADERS)
    unit = f" {r.value_unit}" if r.value_unit else ""

    _merge_whole_widget(tbl, 0, 0, n + 1, _fmt_freq(r.freq_set))
    fci_tint_rows = []
    for i in range(n):
        text = _fmt_num(r.raw_readings[i]) + unit if i < len(r.raw_readings) else ""
        _set_cell(tbl, i, 1, text)
        if i < len(r.raw_readings) and interactive and recompute_row:
            _make_editable(tbl, i, 1, *_edit_raw_reading(recompute_row, r, 0, i, on_value_edited))
        if i < len(r.raw_readings):
            _make_gcn_markable(tbl, i, 1, rows, r, f"raw:{i}", on_value_edited)
        fci_tint_rows.append(i)
    extra_cols = _fill_value_slots(tbl, n, 2, r, 0, n, 2, unit, interactive, recompute_row, on_value_edited,
                                   all_rows=rows)
    _set_cell(tbl, n, 4, r.limit or "")

    row_groups = [(0, n + 1, r)]
    tint = []
    if r.edited:
        tint = [(i, [1]) for i in fci_tint_rows] + [(n, extra_cols)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


def _build_freq_sensitivity(rows, with_checkbox=False, on_toggle=None, with_status=False,
                            on_status_change=None, interactive=True, on_value_edited=None,
                            recompute_row=None, measured_counts=None) -> QTableWidget:
    tbl = _new_table(len(rows), _lay.FREQ_SENSITIVITY_HEADERS)
    tint = []
    for i, r in enumerate(rows):
        unit = f" {r.value_unit}" if r.value_unit else ""
        _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        cols = _fill_value_slots(tbl, i, 1, r, i, 0, 1, unit, interactive, recompute_row, on_value_edited,
                                 all_rows=rows)
        _set_cell(tbl, i, 2, r.limit or "")
        if r.edited:
            tint.append((i, cols))
    _merge_consecutive_widget(tbl, 2, 0, len(rows), [r.limit or "" for r in rows])
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


def _build_freq_error(channel: str):
    def _builder(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                interactive=True, on_value_edited=None, recompute_row=None,
                measured_counts=None) -> QTableWidget:
        tbl = _new_table(len(rows), _lay.freq_error_headers(channel))
        tint = []
        for i, r in enumerate(rows):
            unit = f" {r.value_unit}" if r.value_unit else ""
            _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
            cols = _fill_value_slots(tbl, i, 1, r, i, 0, 2, unit, interactive, recompute_row, on_value_edited,
                                     all_rows=rows)
            if r.edited:
                tint.append((i, cols))
        if rows:
            _merge_whole_widget(tbl, 3, 0, len(rows), rows[0].limit or "")
        row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
        return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                            interactive, tint)
    return _builder


def _build_freq_a8(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                   interactive=True, on_value_edited=None, recompute_row=None,
                   measured_counts=None) -> QTableWidget:
    tbl = _new_table(len(rows), _lay.FREQ_A8_HEADERS)
    tint = []
    for i, r in enumerate(rows):
        unit = f" {r.value_unit}" if r.value_unit else ""
        _set_cell(tbl, i, 0, r.key)
        cols = _fill_value_slots(tbl, i, 1, r, i, 0, 2, unit, interactive, recompute_row, on_value_edited,
                                 all_rows=rows)
        if r.edited:
            tint.append((i, cols))
    if rows:
        _merge_whole_widget(tbl, 3, 0, len(rows), rows[0].limit or "")
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


_POWER_A1_GROUP_SIZE = 5   # khớp scripts/build_generic_seed_templates.py::POWER_A1_GROUP_SIZE


def _build_power_a1(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                    interactive=True, on_value_edited=None, recompute_row=None,
                    measured_counts=None) -> QTableWidget:
    """Khớp ĐÚNG cấu trúc dựng trong scripts/build_generic_seed_templates.py
    (nhánh 'if tid == "A1"' của build_power_bienban): 10 lần đo chia 2 nhóm
    5 cột, TB/Độ KĐBĐ ở 1 dòng riêng cuối bảng (không gộp dọc — cùng lý do
    tránh cho A1 FREQ: tag ô gộp dọc bị đọc xen vào dòng đầu)."""
    r = rows[0]
    measured = (measured_counts[0] if measured_counts and measured_counts[0] is not None
                else len(r.raw_readings))
    group = _POWER_A1_GROUP_SIZE
    n_groups = -(-measured // group) if measured else 0
    tbl = _new_table(n_groups + 1, _lay.power_a1_headers(group))
    unit = f" {r.value_unit}" if r.value_unit else ""

    tint = []
    for g in range(n_groups):
        _set_cell(tbl, g, 0, r.key)
        cols = _fill_value_slots(tbl, g, 1, r, 0, g * group, group, unit, interactive,
                                 recompute_row, on_value_edited, all_rows=rows)
        if r.edited:
            tint.append((g, cols))
    tb_row = n_groups
    _set_cell(tbl, tb_row, 0, "Trung Bình")
    # TB ở cột 1 (đầu khối "lần N", giống bảng docx gộp ngang cột 1..group),
    # Độ KĐBĐ ở ĐÚNG cột header "Độ KĐBĐ" (group+1) — KHÔNG liền kề TB.
    tb_cols = _fill_value_slots(tbl, tb_row, 1, r, 0, measured, 1, unit, interactive,
                                recompute_row, on_value_edited, all_rows=rows)
    kdbd_cols = _fill_value_slots(tbl, tb_row, 1 + group, r, 0, measured + 1, 1, unit, interactive,
                                  recompute_row, on_value_edited, all_rows=rows)
    if r.edited:
        tint.append((tb_row, tb_cols + kdbd_cols))

    row_groups = [(0, n_groups + 1, r)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


def _build_power_a2(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                    interactive=True, on_value_edited=None, recompute_row=None,
                    measured_counts=None) -> QTableWidget:
    raw_n = (measured_counts[0] if measured_counts and measured_counts[0] is not None
             else max((len(r.raw_readings) for r in rows), default=1) or 1)
    tbl = _new_table(len(rows), _lay.power_a2_headers(raw_n))
    tint = []
    for i, r in enumerate(rows):
        unit = f" {r.value_unit}" if r.value_unit else ""
        _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        cols = _fill_value_slots(tbl, i, 1, r, i, 0, raw_n, unit, interactive, recompute_row, on_value_edited,
                                 all_rows=rows)
        extra_cols = _fill_value_slots(tbl, i, 1 + raw_n, r, i, raw_n, 2, unit, interactive,
                                       recompute_row, on_value_edited, all_rows=rows)
        if r.edited:
            tint.append((i, cols + extra_cols))
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


def _build_power_a3(rows, with_checkbox=False, on_toggle=None, with_status=False, on_status_change=None,
                    interactive=True, on_value_edited=None, recompute_row=None,
                    measured_counts=None) -> QTableWidget:
    raw_n = (measured_counts[0] if measured_counts and measured_counts[0] is not None
             else max((len(r.raw_readings) for r in rows), default=1) or 1)
    tbl = _new_table(len(rows), _lay.power_a3_headers(raw_n))
    tint = []
    for i, r in enumerate(rows):
        unit = f" {r.value_unit}" if r.value_unit else ""
        power = _power_set_from_key(r.key)
        _set_cell(tbl, i, 1, _fmt_dbm(power) if power is not None else "")
        cols = _fill_value_slots(tbl, i, 2, r, i, 0, raw_n, unit, interactive, recompute_row, on_value_edited,
                                 all_rows=rows)
        extra_cols = _fill_value_slots(tbl, i, 2 + raw_n, r, i, raw_n, 2, unit, interactive,
                                       recompute_row, on_value_edited, all_rows=rows)
        if r.edited:
            tint.append((i, cols + extra_cols))
    _merge_consecutive_widget(tbl, 0, 0, len(rows), [_fmt_freq(r.freq_set) for r in rows])
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    return _finish_rows(tbl, row_groups, with_checkbox, on_toggle, with_status, on_status_change,
                        interactive, tint)


_TEMPLATE_BUILDERS: dict = {
    "TEMPLATE_FREQ": {
        "A1": _build_freq_a1,
        "A2": _build_freq_sensitivity, "A3": _build_freq_sensitivity, "A4": _build_freq_sensitivity,
        "A5": _build_freq_error("A"), "A6": _build_freq_error("B"), "A7": _build_freq_error("C"),
        "A8": _build_freq_a8,
    },
    "TEMPLATE_POWER": {
        "A1": _build_power_a1, "A2": _build_power_a2, "A3": _build_power_a3,
    },
}


def build_wysiwyg_table(template_id: str, table_id: str, rows: list[TableRow],
                        with_checkbox: bool = False, on_toggle=None,
                        with_status: bool = False, on_status_change=None,
                        interactive: bool = True, on_value_edited=None,
                        empty_message: str = "Chưa có dòng nào được xác nhận",
                        recompute_row=None, measured_counts: list | None = None) -> QTableWidget:
    """Dựng bảng rà soát — thứ tự ưu tiên:
    1. Builder tay riêng trong _TEMPLATE_BUILDERS nếu template đó có đăng ký
       (hiện không có template nào đăng ký).
    2. _build_from_docx_grid — đọc TRỰC TIẾP cấu trúc cột từ chính file
       bienban.docx thật (tiêu đề cột nguyên văn, khớp ĐÚNG vị trí report_val()
       thật) — áp dụng được cho MỌI template data-driven, chỉ cần bảng đã
       gắn tag report_val() trong file Word.
    3. _build_generic — chỉ dùng khi KHÔNG tìm được bảng thật khớp (mẫu mới
       chưa có docx, bảng chưa gắn tag) — tên cột chung "Lần N", không khớp
       docx thật.

    with_status thêm cột 'Đạt/Không đạt' (combobox, ghi vào TableRow.passed)
    — chỉ hỗ trợ rà soát trong app, KHÔNG xuất hiện trong file docx.
    interactive=False vẫn HIỆN checkbox/combobox nhưng khoá lại (disabled)
    — dùng khi bài chưa có kết quả thật (bảng xem trước khung rỗng).
    interactive=True cũng cho double-click sửa tay ô "giá trị đo" — gọi
    on_value_edited() sau khi sửa xong để caller dựng lại bảng (giá trị mới
    đã được ghi thẳng vào TableRow, kèm tính lại error/passed và đánh dấu
    TableRow.edited=True để hiển thị nổi bật). recompute_row(row_index,
    raw_readings) -> (measured, error, limit, passed) BẮT BUỘC phải truyền
    vào để bật sửa tay (xem core/table_engine.py::recompute_row) — không có
    thì ô "giá trị đo" chỉ đọc, không double-click được."""
    if not rows:
        return _empty_table(empty_message)
    get_builders = _TEMPLATE_BUILDERS.get(template_id, {})
    builder = get_builders.get(table_id) if get_builders else None
    if builder is not None:
        return builder(rows, with_checkbox=with_checkbox, on_toggle=on_toggle,
                       with_status=with_status, on_status_change=on_status_change,
                       interactive=interactive, on_value_edited=on_value_edited,
                       recompute_row=recompute_row, measured_counts=measured_counts)
    grid_info = _docx_grid_for(template_id, table_id)
    if grid_info is not None:
        grid, value_cols = grid_info
        return _build_from_docx_grid(rows, grid, value_cols,
                                     with_checkbox=with_checkbox, on_toggle=on_toggle,
                                     with_status=with_status, on_status_change=on_status_change,
                                     interactive=interactive, on_value_edited=on_value_edited,
                                     recompute_row=recompute_row, measured_counts=measured_counts)
    return _build_generic(rows, with_checkbox=with_checkbox, on_toggle=on_toggle,
                          with_status=with_status, on_status_change=on_status_change,
                          interactive=interactive, on_value_edited=on_value_edited,
                          recompute_row=recompute_row, measured_counts=measured_counts)
