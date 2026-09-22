"""
core/xlsx_table_engine.py
===========================
Render Biên Bản/GCN khi mẫu là file Excel (.xlsx) thay vì Word (.docx) —
đường song song với core/table_engine.py::render_with_table_contexts(), tái
dùng NGUYÊN VẸN map_table()/build_all_table_contexts()/build_raw_rows_by_table()
đã có (không quan tâm Biên Bản là docx hay xlsx, chỉ tạo ReportTable/context).

Quy ước tag: quản trị viên gõ TEXT THƯỜNG (không phải công thức '=...') vào 1
ô Excel, TOÀN BỘ nội dung ô (sau strip) là 1 trong:
  report_val('<table_id>')  — giá trị đo THÔ (số thực), tuần tự theo đúng thứ
                               tự raw_readings đã ghi trong descriptor.rows —
                               ghi SỐ THẬT (không phải chuỗi định dạng) vì ô
                               này thường được công thức khác trong sheet
                               tham chiếu tính tiếp (=AVERAGE()/=SQRT()...).
  result('<table_id>')      — Đạt/Không đạt (hoặc giá trị export riêng) —
                               chuỗi hiển thị, giống Word.
  gcn_avg('<table_id>')     — trung bình đã tính (GCN) — chuỗi hiển thị.
  gcn_error('<table_id>')   — sai số/hiệu chỉnh (GCN) — chuỗi hiển thị.
  gcn_limit('<table_id>')   — ngưỡng khai báo (GCN) — chuỗi hiển thị.
Mỗi ô CHỈ chứa đúng 1 marker (không mix với chữ tĩnh khác) — ô Excel là đơn vị
dữ liệu trọn vẹn, khác Word phải ráp nhiều "run" trong 1 đoạn văn.

Mọi công thức/định dạng khác trong sheet giữ NGUYÊN — không đụng tới.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import openpyxl

from core.session import CalibrationSession
from core import table_engine

_MARKER_RE = re.compile(r"^\s*(report_val|gcn_avg|gcn_error|gcn_limit|result)\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)\s*$")


def _flatten_raw(rows: list) -> list:
    return [v for r in rows for v in r.raw_readings]


def render_xlsx_with_table_contexts(session: CalibrationSession, descriptors: list,
                                     template_path, output_path) -> Path:
    """Render 1 file .xlsx theo đúng quy ước report_val()/result()/gcn_*()
    ở trên — quét TOÀN BỘ ô đã dùng của mọi sheet (trái→phải, trên→dưới,
    tự giới hạn theo vùng dùng thật, không tràn), ô nào khớp marker thì ghi
    đè giá trị vào, giữ nguyên mọi ô/công thức khác."""
    output_path = Path(output_path)
    raw_by_table = table_engine.build_raw_rows_by_table(session, descriptors)
    ctx_by_table = table_engine.build_all_table_contexts(session, descriptors)
    raw_cursors = {tid: iter(_flatten_raw(rows)) for tid, rows in raw_by_table.items()}

    wb = openpyxl.load_workbook(str(template_path), data_only=False)

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not isinstance(v, str):
                    continue
                m = _MARKER_RE.match(v)
                if not m:
                    continue
                fn_name, table_id = m.group(1), m.group(2)
                if fn_name == "report_val":
                    it = raw_cursors.get(table_id)
                    cell.value = next(it, None) if it is not None else None
                    continue
                tctx = ctx_by_table.get(table_id)
                if tctx is None:
                    cell.value = None
                    continue
                val = tctx.get(fn_name)
                result = val() if callable(val) else val
                cell.value = result if result else None

    # Ép Excel tự tính lại MỌI công thức khi mở file kết quả — phòng hờ file
    # mẫu không tự bật fullCalcOnLoad (openpyxl không tự tính công thức nên
    # không có cached value nào để hiện tạm, nếu thiếu cờ này 1 số máy có
    # thể hiện 0/trống cho tới khi người dùng tự F9).
    if wb.calculation is not None:
        wb.calculation.fullCalcOnLoad = True

    wb.save(str(output_path))
    return output_path
