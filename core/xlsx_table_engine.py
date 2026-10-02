"""
core/xlsx_table_engine.py
===========================
Render Biên Bản/GCN khi mẫu là file Excel (.xlsx) thay vì Word (.docx) —
đường song song với core/table_engine.py::render_with_table_contexts(), tái
dùng NGUYÊN VẸN map_table()/build_all_table_contexts()/build_raw_rows_by_table()
đã có (không quan tâm Biên Bản là docx hay xlsx, chỉ tạo ReportTable/context).

Quy ước tag: quản trị viên gõ TEXT THƯỜNG (không phải công thức '=...') vào 1
ô Excel, gồm 2 nhóm:

  report_val('<table_id>')  — PHẢI chiếm TRỌN ô (không mix chữ tĩnh khác) —
                               giá trị đo THÔ (số thực), tuần tự theo đúng thứ
                               tự raw_readings đã ghi trong descriptor.rows —
                               ghi SỐ THẬT (không phải chuỗi định dạng) vì ô
                               này thường được công thức khác trong sheet
                               tham chiếu tính tiếp (=AVERAGE()/=SQRT()...).
                               Lý do bắt buộc chiếm trọn ô: nếu mix với chữ
                               khác, cả ô buộc phải thành CHUỖI (không còn là
                               số), công thức tham chiếu nó sẽ lỗi/tính sai.

  result('<table_id>')      — Đạt/Không đạt (hoặc giá trị export riêng).
  gcn_avg('<table_id>')     — trung bình đã tính (GCN).
  gcn_error('<table_id>')   — sai số/hiệu chỉnh (GCN).
  gcn_limit('<table_id>')   — ngưỡng khai báo (GCN).
  header('<key>')           — thông tin chung của PHIÊN (không gắn với bảng
                               nào) — DUT/ngày/người ký..., đúng field đặt tên
                               trong core/generic_report_context.py::header.*
                               (tương đương {{ header.<key> }} bên Word), vd
                               header('name'), header('serial'), header('sign_date').
                               4 loại này LUÔN là CHUỖI hiển thị (không dùng
                               trong công thức số) nên được phép GÕ CHUNG với
                               chữ tĩnh khác trong CÙNG 1 ô, ví dụ ô có đúng
                               nội dung "Nhiệt độ: header('temperature')" sẽ
                               ra "Nhiệt độ: 23 °C" — giữ nguyên phần chữ
                               tĩnh, chỉ thay phần header('...') bằng giá trị
                               thật (có thể có NHIỀU marker trong 1 ô).

Mọi công thức/định dạng khác trong sheet giữ NGUYÊN — không đụng tới.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import openpyxl

from core.session import CalibrationSession
from core import table_engine

# report_val PHẢI là toàn bộ nội dung ô (xem lý do ở docstring trên).
_REPORT_VAL_RE = re.compile(r"^\s*report_val\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)\s*$")
# 4 loại còn lại CHO PHÉP nhúng trong chuỗi, tìm MỌI lần xuất hiện trong ô.
_EMBED_MARKER_RE = re.compile(r"(gcn_avg|gcn_error|gcn_limit|result|header)\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)")


def _flatten_raw(rows: list) -> list:
    return [v for r in rows for v in r.raw_readings]


def render_xlsx_with_table_contexts(session: CalibrationSession, descriptors: list,
                                     template_path, output_path,
                                     meta_context_fn: Optional[Callable[[CalibrationSession], dict]] = None) -> Path:
    """Render 1 file .xlsx theo đúng quy ước report_val()/result()/gcn_*()/
    header() ở trên — quét TOÀN BỘ ô đã dùng của mọi sheet (trái→phải, trên→
    dưới, tự giới hạn theo vùng dùng thật, không tràn), ô nào khớp marker thì
    ghi đè giá trị vào, giữ nguyên mọi ô/công thức khác.

    meta_context_fn: như core/table_engine.py::render_with_table_contexts
    (Word) — hàm trả {"header": {...}, ...} từ core/generic_report_context.py.
    Bỏ trống (None) nếu mẫu không có ô header('...') nào — vẫn hoạt động như
    trước, không bắt buộc mọi mẫu Excel phải có."""
    output_path = Path(output_path)
    raw_by_table = table_engine.build_raw_rows_by_table(session, descriptors)
    ctx_by_table = table_engine.build_all_table_contexts(session, descriptors)
    raw_cursors = {tid: iter(_flatten_raw(rows)) for tid, rows in raw_by_table.items()}
    header_ctx = meta_context_fn(session)["header"] if meta_context_fn else {}

    # LƯU Ý RÒ RỈ BỘ NHỚ (đã gặp thật — khách báo RAM tăng nhanh khi dùng
    # mẫu Excel): openpyxl Workbook giữ tham chiếu CHÉO giữa cell/row/
    # worksheet/style manager (reference cycle), KHÔNG tự giải phóng ngay
    # bằng refcounting thường của Python, và còn giữ 1 file handle (đọc
    # .xlsx qua zipfile) cho tới khi gọi wb.close() tường minh. Hàm này được
    # gọi lại MỖI LẦN bấm "Xem nhanh"/"Xuất Biên Bản" — thiếu wb.close() ở
    # đây khiến RAM cộng dồn dần theo từng lần bấm trong 1 phiên làm việc.
    # try/finally đảm bảo đóng workbook dù có lỗi giữa chừng.
    def _resolve_one(fn_name: str, arg: str) -> str:
        """Tính giá trị CHUỖI cho 1 marker gcn_*/result/header — dùng chung
        cho cả 2 nhánh (ô chỉ có marker, hoặc marker nhúng trong chữ tĩnh)."""
        if fn_name == "header":
            return str(header_ctx.get(arg, "") or "")
        tctx = ctx_by_table.get(arg)
        if tctx is None:
            return ""
        val = tctx.get(fn_name)
        result = val() if callable(val) else val
        return str(result) if result else ""

    wb = openpyxl.load_workbook(str(template_path), data_only=False)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    v = cell.value
                    if not isinstance(v, str):
                        continue

                    m = _REPORT_VAL_RE.match(v)
                    if m:
                        it = raw_cursors.get(m.group(1))
                        cell.value = next(it, None) if it is not None else None
                        continue

                    if not _EMBED_MARKER_RE.search(v):
                        continue
                    new_v = _EMBED_MARKER_RE.sub(
                        lambda mo: _resolve_one(mo.group(1), mo.group(2)), v)
                    # Chỉ toàn marker (không chữ tĩnh nào khác) và không tra
                    # được giá trị -> None, giữ đúng hành vi cũ (ô trống hẳn,
                    # không phải chuỗi rỗng). Có chữ tĩnh kèm theo thì giữ
                    # nguyên phần chữ đó dù giá trị động có rỗng hay không.
                    cell.value = new_v if new_v.strip() else None

        # Ép Excel tự tính lại MỌI công thức khi mở file kết quả — phòng hờ
        # file mẫu không tự bật fullCalcOnLoad (openpyxl không tự tính công
        # thức nên không có cached value nào để hiện tạm, nếu thiếu cờ này 1
        # số máy có thể hiện 0/trống cho tới khi người dùng tự F9).
        if wb.calculation is not None:
            wb.calculation.fullCalcOnLoad = True

        wb.save(str(output_path))
    finally:
        wb.close()
    return output_path
