"""
gui/report_preview.py
======================
Dựng QTableWidget cho panel "Xem trước báo cáo" ở Bước 3 — mô phỏng ĐÚNG
cột/gộp ô như bảng thật trong core/report_generator.py cho từng loại bảng
A1–A8, dùng lại chính các hàm định dạng số đã có ở đó để preview không bao
giờ lệch pha với file docx thực tế xuất ra.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
from PyQt5.QtCore import Qt

from core.session import TableRow
from core.report_generator import (
    _fmt_freq, _fmt_hz_measured, _fmt_period, _fmt_mv, _fmt_dbm, _sci,
)


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


# ---------------------------------------------------------------------------
# A1 — Sai số bộ dao động thạch anh (mô phỏng report_generator._add_table_a1)
# ---------------------------------------------------------------------------

def _build_a1(rows: list[TableRow]) -> QTableWidget:
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


def _build_sensitivity(rows: list[TableRow], value_fmt) -> QTableWidget:
    tbl = _new_table(len(rows), ["Tần số thiết lập", "Độ nhạy đo được", "Độ nhạy cho phép"])
    _fill_grouped_limit(tbl, rows, value_fmt)
    return _finish(tbl)


# ---------------------------------------------------------------------------
# A5/A6/A7 — Sai số đo tần số
# ---------------------------------------------------------------------------

def _build_freq_error(rows: list[TableRow]) -> QTableWidget:
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
    return _finish(tbl)


# ---------------------------------------------------------------------------
# A8 — Sai số đo chu kỳ
# ---------------------------------------------------------------------------

def _build_period_error(rows: list[TableRow]) -> QTableWidget:
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
    return _finish(tbl)


_BUILDERS = {
    "A1": _build_a1,
    "A2": lambda rows: _build_sensitivity(rows, _fmt_mv),
    "A3": lambda rows: _build_sensitivity(rows, _fmt_mv),
    "A4": lambda rows: _build_sensitivity(rows, _fmt_dbm),
    "A5": _build_freq_error,
    "A6": _build_freq_error,
    "A7": _build_freq_error,
    "A8": _build_period_error,
}


def build_wysiwyg_table(table_id: str, rows: list[TableRow]) -> QTableWidget:
    """Dựng bảng preview khớp đúng layout docx thật của table_id (A1..A8)."""
    if not rows:
        return _empty_table("Chưa có dòng nào được xác nhận")
    builder = _BUILDERS.get(table_id)
    if builder is None:
        return _empty_table(f"Không rõ định dạng bảng '{table_id}'")
    return builder(rows)
