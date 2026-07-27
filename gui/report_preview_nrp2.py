"""
gui/report_preview_nrp2.py
============================
Dựng QTableWidget mô phỏng ĐÚNG cột/gộp ô như bảng thật trong
core/report_generator_nrp2.py — cụ thể là bảng BIÊN BẢN (Phụ lục A), có
ghi từng lần đo (không phải bảng GCN rút gọn), vì đây là bảng đầy đủ nhất
để người dùng rà soát trước khi xác nhận. TÁCH RIÊNG khỏi
gui/report_preview.py vì cùng mã bảng "A1"/"A2"/"A3" nhưng ý nghĩa cột
hoàn toàn khác CNT-90XL.
"""

from __future__ import annotations

from core.session import TableRow
from core.report_generator import _fmt_freq, _fmt_dbm
from core.report_generator_nrp2 import _fmt_w, _power_set_from_key, _A1_N_LAN
from gui.report_preview import (
    _new_table, _set_cell, _finish, _add_checkbox_column, _add_status_column,
)


def _build_a1_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                   with_status: bool = False, on_status_change=None,
                   interactive: bool = True):
    """Đúng mẫu Biên Bản: 1 dòng, cột 'lần 1'..'lần 10' nằm ngang giữa Công
    suất chuẩn và Độ KĐBĐ (giống cách trải cột của Bảng A2/A3)."""
    row0 = rows[0]
    raws = row0.raw_readings or []
    headers = ["Công suất\nchuẩn"] + [f"lần {i + 1}" for i in range(_A1_N_LAN)] + ["Độ\nKĐBĐ"]
    tbl = _new_table(1, headers)
    _set_cell(tbl, 0, 0, "1 mW")
    for i in range(_A1_N_LAN):
        if i < len(raws):
            _set_cell(tbl, 0, 1 + i, _fmt_w(raws[i]))
    _set_cell(tbl, 0, 1 + _A1_N_LAN, row0.limit)
    row_groups = [(0, 1, row0)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


def _build_a2_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                   with_status: bool = False, on_status_change=None,
                   interactive: bool = True):
    """Đúng mẫu Biên Bản: Tần số | lần 1..5 | TB | Độ KĐBĐ (8 cột)."""
    headers = ["Tần số thiết lập\n(mức công suất 0 dBm)",
               "lần 1", "lần 2", "lần 3", "lần 4", "lần 5", "TB", "Độ KĐBĐ"]
    tbl = _new_table(len(rows), headers)
    for i, r in enumerate(rows):
        if r.freq_set:
            _set_cell(tbl, i, 0, _fmt_freq(r.freq_set))
        for k in range(5):
            if k < len(r.raw_readings):
                _set_cell(tbl, i, 1 + k, _fmt_dbm(r.raw_readings[k]))
        if r.value_measured is not None:
            _set_cell(tbl, i, 6, _fmt_dbm(r.value_measured))
        _set_cell(tbl, i, 7, r.limit)
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


def _build_a3_nrp2(rows: list[TableRow], with_checkbox: bool = False, on_toggle=None,
                   with_status: bool = False, on_status_change=None,
                   interactive: bool = True):
    """Đúng mẫu Biên Bản: Tần số (gộp theo nhóm) | Công suất chuẩn | lần 1..5
    | TB | Độ KĐBĐ (9 cột)."""
    headers = ["Tần số\nthiết lập", "Công suất\nchuẩn (dBm)",
               "lần 1", "lần 2", "lần 3", "lần 4", "lần 5", "TB", "Độ\nKĐBĐ"]
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
        for k in range(5):
            if k < len(r.raw_readings):
                _set_cell(tbl, i, 2 + k, _fmt_dbm(r.raw_readings[k]))
        if r.value_measured is not None:
            _set_cell(tbl, i, 7, _fmt_dbm(r.value_measured))
        _set_cell(tbl, i, 8, r.limit)

    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return _finish(tbl)


NRP2_BUILDERS = {
    "A1": _build_a1_nrp2,
    "A2": _build_a2_nrp2,
    "A3": _build_a3_nrp2,
}
