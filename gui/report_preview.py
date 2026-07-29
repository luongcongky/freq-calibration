"""
gui/report_preview.py
======================
Dựng QTableWidget mô phỏng ĐÚNG cột/gộp ô như bảng thật trong file docx cho
từng loại bảng, dùng ở cả Bước 2 (rà soát + xác nhận từng dòng, có cột
checkbox) và Bước 3 (xem trước báo cáo, không có checkbox).

Mỗi template report có layout bảng riêng (vd "A2" của CNT-90XL là độ nhạy
mVrms, nhưng "A2" của NRP2 là công suất/số hiệu chỉnh) — build_wysiwyg_table
nhận template_id để tra đúng bộ builder, tránh lẫn lộn giữa các template
dùng chung mã bảng "A1".."A8".
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox, QComboBox, QWidget, QHBoxLayout, QApplication,
)
from PyQt5.QtCore import Qt

from core.session import TableRow
from core.report_generator import (
    _fmt_freq, _fmt_hz_measured, _fmt_period, _fmt_mv, _fmt_dbm, _sci,
)
from gui.widgets import CheckBoxHeader


class _StatusCombo(QComboBox):
    """QComboBox thường: khi đặt trong ô đã setSpan() của QTableWidget (bảng
    A1 gộp nhiều dòng "lần đo" vào 1 combo), widget bị Qt kéo giãn theo toàn
    bộ vùng gộp — geometry() của combo không còn khớp với vị trí nó THỰC SỰ
    hiển thị trên màn hình, khiến popup tính theo self.rect() bị lệch xa.
    Thay vào đó, mở popup ngay tại VỊ TRÍ CHUỘT VỪA CLICK (đáng tin cậy hơn
    geometry của widget) — ưu tiên mở SANG PHẢI, tự lật sang TRÁI nếu không
    đủ chỗ tới mép màn hình; lật lên trên nếu không đủ chỗ phía dưới."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._click_pos = None

    def mousePressEvent(self, event):
        self._click_pos = event.globalPos()
        super().mousePressEvent(event)

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        pos = self._click_pos or self.mapToGlobal(self.rect().bottomLeft())
        screen = QApplication.screenAt(pos) or self.screen()
        avail = screen.availableGeometry() if screen else None
        w, h = popup.width(), popup.height()
        x, y = pos.x(), pos.y()
        if avail:
            if x + w > avail.right():
                x = pos.x() - w             # không đủ chỗ bên phải -> mở sang trái
            if y + h > avail.bottom():
                y = pos.y() - h             # không đủ chỗ phía dưới -> mở lên trên
        popup.move(x, y)


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
        combo = _StatusCombo()
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


# ---------------------------------------------------------------------------
# A1 — Sai số bộ dao động thạch anh (mô phỏng report_generator._add_table_a1)
# ---------------------------------------------------------------------------

def _build_a1(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
             with_status: bool = False, on_status_change=None,
             interactive: bool = True) -> QTableWidget:
    row0 = rows[0]
    raws = row0.raw_readings or []
    n = max(len(raws), 1)
    headers = ["Tần số\nthiết lập", "Tần số đo được\ntrên CNT-90XL (fCi)",
               "Tần số đo được\ntrên CNT-90XL (fC)", "Sai số tần số\n(δf)", "Sai số\ncho phép"]
    tbl = _new_table(n, headers)
    for i in range(n):
        if i < len(raws):
            _set_cell(tbl, i, 1, _fmt_hz_measured(raws[i]))
    tbl.setSpan(0, 0, n, 1)
    tbl.setSpan(0, 2, n, 1)
    tbl.setSpan(0, 3, n, 1)
    tbl.setSpan(0, 4, n, 1)
    _set_cell(tbl, 0, 0, _fmt_freq(row0.freq_set or 10e6))
    _set_cell(tbl, 0, 2, _fmt_hz_measured(row0.value_measured) if row0.value_measured else "")
    _set_cell(tbl, 0, 3, f"± {_sci(row0.error)}" if row0.error is not None else "")
    _set_cell(tbl, 0, 4, row0.limit or "± 2,4×10⁻⁷")
    row_groups = [(0, n, row0)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


# ---------------------------------------------------------------------------
# A2/A3/A4 — Độ nhạy đầu vào (mVrms hoặc dBm), gộp cột giới hạn theo nhóm
# ---------------------------------------------------------------------------

def _fill_grouped_limit(tbl: QTableWidget, rows: list[TableRow], value_fmt):
    for i, r in enumerate(rows):
        if r.freq_set:
            _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        if r.value_measured is not None:
            _set_cell(tbl, i, 1, value_fmt(r.value_measured))
    start = 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i].limit != rows[start].limit:
            if i - start > 1:
                tbl.setSpan(start, 2, i - start, 1)
            _set_cell(tbl, start, 2, rows[start].limit)
            start = i


def _build_sensitivity(rows: list[TableRow], value_fmt,
                       with_checkbox: bool = False, on_toggle=None,
                       with_status: bool = False, on_status_change=None,
                       interactive: bool = True) -> QTableWidget:
    tbl = _new_table(len(rows), ["Tần số thiết lập", "Độ nhạy đo được", "Độ nhạy cho phép"])
    _fill_grouped_limit(tbl, rows, value_fmt)
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


# ---------------------------------------------------------------------------
# A5/A6/A7 — Sai số đo tần số
# ---------------------------------------------------------------------------

def _build_freq_error(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                      with_status: bool = False, on_status_change=None,
                      interactive: bool = True) -> QTableWidget:
    headers = ["Tần số\nthiết lập", "Tần số đo được\n(fđo)", "Sai số đo\ntần số (δf)", "Sai số\ncho phép"]
    tbl = _new_table(len(rows), headers)
    for i, r in enumerate(rows):
        if r.freq_set:
            _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        if r.value_measured:
            _set_cell(tbl, i, 1, _fmt_hz_measured(r.value_measured))
        if r.error is not None:
            _set_cell(tbl, i, 2, _sci(r.error))
    if rows:
        tbl.setSpan(0, 3, len(rows), 1)
        _set_cell(tbl, 0, 3, rows[0].limit or "± 2,4×10⁻⁷")
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


# ---------------------------------------------------------------------------
# A8 — Sai số đo chu kỳ
# ---------------------------------------------------------------------------

def _build_period_error(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                        with_status: bool = False, on_status_change=None,
                        interactive: bool = True) -> QTableWidget:
    headers = ["Tần số (chu kỳ)\nthiết lập", "Chu kỳ\nđo được (Tđo)",
               "Sai số đo\n(δT)", "Sai số cho phép\n(δTcp)"]
    tbl = _new_table(len(rows), headers)
    for i, r in enumerate(rows):
        _set_cell(tbl, i, 0, r.key)
        if r.value_measured:
            _set_cell(tbl, i, 1, _fmt_period(r.value_measured))
        if r.error is not None:
            _set_cell(tbl, i, 2, _sci(r.error))
    if rows:
        tbl.setSpan(0, 3, len(rows), 1)
        _set_cell(tbl, 0, 3, rows[0].limit or "± 2,4×10⁻⁷")
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


_BUILDERS = {
    "A1": _build_a1,
    "A2": lambda rows, **kw: _build_sensitivity(rows, _fmt_mv, **kw),
    "A3": lambda rows, **kw: _build_sensitivity(rows, _fmt_mv, **kw),
    "A4": lambda rows, **kw: _build_sensitivity(rows, _fmt_dbm, **kw),
    "A5": _build_freq_error,
    "A6": _build_freq_error,
    "A7": _build_freq_error,
    "A8": _build_period_error,
}


def _nrp2_builders() -> dict:
    from gui.report_preview_nrp2 import NRP2_BUILDERS
    return NRP2_BUILDERS


_TEMPLATE_BUILDERS = {
    "QTKD_2461_CNT90XL": lambda: _BUILDERS,
    "QTHC_2515_NRP2": _nrp2_builders,
}


def build_wysiwyg_table(template_id: str, table_id: str, rows: list[TableRow],
                        with_checkbox: bool = False, on_toggle=None,
                        with_status: bool = False, on_status_change=None,
                        interactive: bool = True,
                        empty_message: str = "Chưa có dòng nào được xác nhận") -> QTableWidget:
    """Dựng bảng khớp đúng layout docx thật của table_id, theo đúng template
    đang dùng (mỗi template có thể định nghĩa lại ý nghĩa mã bảng A1..A8).

    with_status thêm cột 'Đạt/Không đạt' (combobox, ghi vào TableRow.passed)
    — chỉ hỗ trợ rà soát trong app, KHÔNG xuất hiện trong file docx.
    interactive=False vẫn HIỆN checkbox/combobox nhưng khoá lại (disabled)
    — dùng khi bài chưa có kết quả thật (bảng xem trước khung rỗng)."""
    if not rows:
        return _empty_table(empty_message)
    get_builders = _TEMPLATE_BUILDERS.get(template_id, _TEMPLATE_BUILDERS["QTKD_2461_CNT90XL"])
    builder = get_builders().get(table_id)
    if builder is None:
        return _empty_table(f"Không rõ định dạng bảng '{table_id}'")
    return builder(rows, with_checkbox=with_checkbox, on_toggle=on_toggle,
                   with_status=with_status, on_status_change=on_status_change,
                   interactive=interactive)
