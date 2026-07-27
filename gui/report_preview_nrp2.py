"""
gui/report_preview_nrp2.py
============================
Dựng QTableWidget mô phỏng ĐÚNG cột/gộp ô như bảng thật trong
core/report_generator_nrp2.py (template QTHC 2.515:2021 — NRP2), dùng cho
Bước 2 (rà soát/xác nhận, có checkbox) và Bước 3 (xem trước, không
checkbox) của wizard. TÁCH RIÊNG khỏi gui/report_preview.py vì cùng mã
bảng "A1"/"A2"/"A3" nhưng ý nghĩa cột hoàn toàn khác CNT-90XL.
"""

from __future__ import annotations

from core.session import TableRow
from core.report_generator import _fmt_freq, _fmt_dbm
from core.report_generator_nrp2 import _fmt_w, _fmt_correction
from gui.report_preview import _new_table, _set_cell, _finish, _add_checkbox_column


def _build_a1_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None):
    row0 = rows[0]
    raws = row0.raw_readings or []
    n = max(len(raws), 1)
    headers = ["Công suất\nchuẩn", "Công suất đo được\ntrên NRVD (W)",
               "Công suất TB\nđo được (W)", "Số hiệu\nchỉnh", "Độ\nKĐBĐ"]
    tbl = _new_table(n, headers)
    for i in range(n):
        if i < len(raws):
            _set_cell(tbl, i, 1, _fmt_w(raws[i]))
    for col in (0, 2, 3, 4):
        tbl.setSpan(0, col, n, 1)
    _set_cell(tbl, 0, 0, "1 mW")
    _set_cell(tbl, 0, 2, _fmt_w(row0.value_measured) if row0.value_measured is not None else "")
    _set_cell(tbl, 0, 3, _fmt_correction(row0.error, "mW"))
    _set_cell(tbl, 0, 4, row0.limit)
    if with_checkbox:
        _add_checkbox_column(tbl, [(0, n, row0)], on_toggle)
    return _finish(tbl)


def _build_a2_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None):
    tbl = _new_table(len(rows), ["Tần số thiết lập", "Công suất đo được\ntrên NRP2 (dBm)",
                                 "Số hiệu chỉnh", "Độ KĐBĐ"])
    for i, r in enumerate(rows):
        if r.freq_set:
            _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        if r.value_measured is not None:
            _set_cell(tbl, i, 1, _fmt_dbm(r.value_measured))
        _set_cell(tbl, i, 2, _fmt_correction(r.error, "dB"))
        _set_cell(tbl, i, 3, r.limit)
    if with_checkbox:
        _add_checkbox_column(tbl, [(i, i + 1, r) for i, r in enumerate(rows)], on_toggle)
    return _finish(tbl)


def _power_set_from_key(key: str):
    if key and "_" in key:
        try:
            return float(key.rsplit("_", 1)[1].replace("dBm", ""))
        except ValueError:
            return None
    return None


def _build_a3_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None):
    headers = ["Tần số\nthiết lập", "Công suất chuẩn\ntrên NRP2 (dBm)",
               "Công suất TB\nđo được (dBm)", "Số hiệu\nchỉnh", "Độ\nKĐBĐ"]
    tbl = _new_table(len(rows), headers)

    start = 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i].freq_set != rows[start].freq_set:
            if i - start > 1:
                tbl.setSpan(start, 0, i - start, 1)
            _set_cell(tbl, start, 0, _fmt_freq(rows[start].freq_set))
            start = i

    for i, r in enumerate(rows):
        power_set = _power_set_from_key(r.key)
        if power_set is not None:
            _set_cell(tbl, i, 1, _fmt_dbm(power_set))
        if r.value_measured is not None:
            _set_cell(tbl, i, 2, _fmt_dbm(r.value_measured))
        _set_cell(tbl, i, 3, _fmt_correction(r.error, "dB"))
        _set_cell(tbl, i, 4, r.limit)

    if with_checkbox:
        _add_checkbox_column(tbl, [(i, i + 1, r) for i, r in enumerate(rows)], on_toggle)
    return _finish(tbl)


NRP2_BUILDERS = {
    "A1": _build_a1_nrp2,
    "A2": _build_a2_nrp2,
    "A3": _build_a3_nrp2,
}
