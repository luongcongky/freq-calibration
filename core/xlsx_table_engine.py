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

CÁCH GHI — KHÔNG dùng wb.save() của openpyxl:
  openpyxl đọc rồi lưu lại NGUYÊN FILE sẽ làm mất ảnh nổi (trừ khi có cài
  Pillow) VÀ LUÔN LUÔN làm mất textbox/đường kẻ chữ ký/ảnh trong header trang
  (openpyxl không đọc/giữ được các đối tượng vẽ kiểu VML legacy dùng cho
  header) — biên bản/GCN thật của khách hàng thường có đúng những thứ này
  (xem báo cáo lỗi #1, #2). Thay vào đó, hàm render_xlsx_with_table_contexts
  chỉ dùng openpyxl ở chế độ CHỈ ĐỌC (read_only=True) để xác định CẦN ghi gì
  vào ô nào, rồi vá trực tiếp đoạn XML của riêng (các) ô đó ngay trong file
  .xlsx gốc (zip) — mọi phần khác của file (drawing, vmlDrawing, media,
  header/footer, style...) được copy byte-for-byte, không đụng tới.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape as _xml_escape

import openpyxl

from core.session import CalibrationSession
from core import table_engine

# report_val PHẢI là toàn bộ nội dung ô (xem lý do ở docstring trên).
_REPORT_VAL_RE = re.compile(r"^\s*report_val\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)\s*$")
# 4 loại còn lại CHO PHÉP nhúng trong chuỗi, tìm MỌI lần xuất hiện trong ô.
_EMBED_MARKER_RE = re.compile(r"(gcn_avg|gcn_error|gcn_limit|result|header)\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)")


def _flatten_raw(rows: list) -> list:
    return [v for r in rows for v in r.raw_readings]


# ---------------------------------------------------------------------------
# Vá trực tiếp XML trong zip .xlsx — xem docstring đầu file ("CÁCH GHI").
# ---------------------------------------------------------------------------

def _tag_attr(tag: str, name: str) -> Optional[str]:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else None


def _sheet_name_to_xml_path(zf: zipfile.ZipFile) -> dict[str, str]:
    """{tên sheet (ws.title) -> "xl/worksheets/sheetN.xml"} — tra qua
    xl/workbook.xml (tên -> r:id) rồi xl/_rels/workbook.xml.rels (r:id ->
    đường dẫn thật), KHÔNG dựa vào vị trí/tên file sheetN.xml vì thứ tự tab
    không nhất thiết khớp số N."""
    workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
    rels_xml = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")

    name_to_rid = {}
    for tag in re.findall(r"<sheet\b[^>]*/>", workbook_xml):
        name, rid = _tag_attr(tag, "name"), _tag_attr(tag, "r:id")
        if name and rid:
            name_to_rid[name] = rid

    rid_to_target = {}
    for tag in re.findall(r"<Relationship\b[^>]*/>", rels_xml):
        rid, target = _tag_attr(tag, "Id"), _tag_attr(tag, "Target")
        if rid and target:
            rid_to_target[rid] = target

    result = {}
    for name, rid in name_to_rid.items():
        target = rid_to_target.get(rid)
        if not target:
            continue
        result[name] = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    return result


def _format_cell_value_xml(coord: str, attrs: str, value) -> str:
    """Dựng lại đoạn XML <c> cho 1 ô, GIỮ NGUYÊN mọi attribute khác (quan
    trọng nhất là s="..." — chỉ số định dạng ô), chỉ thay phần giá trị/loại."""
    cleaned_attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
    if value is None:
        return f'<c r="{coord}"{cleaned_attrs}/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{coord}"{cleaned_attrs}><v>{value}</v></c>'
    text = _xml_escape(str(value))
    return f'<c r="{coord}"{cleaned_attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _patch_sheet_xml(xml_text: str, replacements: dict[str, object]) -> str:
    for coord, value in replacements.items():
        pattern = re.compile(rf'<c r="{re.escape(coord)}"([^>]*?)(?:/>|>(?:.*?)</c>)', re.DOTALL)

        def _sub(m: "re.Match[str]", _coord=coord, _value=value) -> str:
            return _format_cell_value_xml(_coord, m.group(1), _value)

        xml_text, n = pattern.subn(_sub, xml_text, count=1)
        if n == 0:
            raise ValueError(f"Không tìm thấy ô {coord} trong file mẫu Excel khi ghi báo cáo.")
    return xml_text


def _force_full_calc_on_load(workbook_xml: str) -> str:
    """Ép Excel tự tính lại MỌI công thức khi mở file kết quả — phòng hờ file
    mẫu không tự bật fullCalcOnLoad (ô bị vá ở trên không có cached value nào
    nên 1 số máy có thể hiện 0/trống cho tới khi người dùng tự F9)."""
    def _patch(m: "re.Match[str]") -> str:
        tag = m.group(0)
        if 'fullCalcOnLoad="1"' in tag:
            return tag
        if 'fullCalcOnLoad="' in tag:
            return re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
        return tag[:-2] + ' fullCalcOnLoad="1"/>'

    new_xml, n = re.subn(r"<calcPr\b[^>]*/>", _patch, workbook_xml, count=1)
    if n:
        return new_xml
    return workbook_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')


def _write_patched_xlsx(template_path, output_path, replacements: dict[str, dict[str, object]]) -> None:
    with zipfile.ZipFile(str(template_path), "r") as src:
        sheet_paths = _sheet_name_to_xml_path(src)
        workbook_xml = _force_full_calc_on_load(src.read("xl/workbook.xml").decode("utf-8"))
        target_path_by_sheet = {
            sheet_paths[name]: repl for name, repl in replacements.items() if name in sheet_paths
        }

        with zipfile.ZipFile(str(output_path), "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "xl/workbook.xml":
                    data = workbook_xml.encode("utf-8")
                elif item.filename in target_path_by_sheet:
                    data = _patch_sheet_xml(data.decode("utf-8"), target_path_by_sheet[item.filename]).encode("utf-8")
                dst.writestr(item, data)


def render_xlsx_with_table_contexts(session: CalibrationSession, descriptors: list,
                                     template_path, output_path,
                                     meta_context_fn: Optional[Callable[[CalibrationSession], dict]] = None) -> Path:
    """Render 1 file .xlsx theo đúng quy ước report_val()/result()/gcn_*()/
    header() ở trên — quét TOÀN BỘ ô đã dùng của mọi sheet (trái→phải, trên→
    dưới, tự giới hạn theo vùng dùng thật, không tràn), ô nào khớp marker thì
    ghi đè giá trị vào, giữ nguyên mọi ô/công thức/ảnh/header khác.

    meta_context_fn: như core/table_engine.py::render_with_table_contexts
    (Word) — hàm trả {"header": {...}, ...} từ core/generic_report_context.py.
    Bỏ trống (None) nếu mẫu không có ô header('...') nào — vẫn hoạt động như
    trước, không bắt buộc mọi mẫu Excel phải có."""
    output_path = Path(output_path)
    raw_by_table = table_engine.build_raw_rows_by_table(session, descriptors)
    ctx_by_table = table_engine.build_all_table_contexts(session, descriptors)
    raw_cursors = {tid: iter(_flatten_raw(rows)) for tid, rows in raw_by_table.items()}
    header_ctx = meta_context_fn(session)["header"] if meta_context_fn else {}

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

    # CHỈ ĐỌC (read_only=True — nhẹ hơn, không dựng toàn bộ style/drawing
    # manager) để xác định ô nào cần ghi gì — xem docstring đầu file.
    replacements: dict[str, dict[str, object]] = {}
    wb = openpyxl.load_workbook(str(template_path), data_only=False, read_only=True)
    try:
        for ws in wb.worksheets:
            sheet_repl: dict[str, object] = {}
            for row in ws.iter_rows():
                for cell in row:
                    v = cell.value
                    if not isinstance(v, str):
                        continue

                    m = _REPORT_VAL_RE.match(v)
                    if m:
                        it = raw_cursors.get(m.group(1))
                        sheet_repl[cell.coordinate] = next(it, None) if it is not None else None
                        continue

                    if not _EMBED_MARKER_RE.search(v):
                        continue
                    new_v = _EMBED_MARKER_RE.sub(
                        lambda mo: _resolve_one(mo.group(1), mo.group(2)), v)
                    # Chỉ toàn marker (không chữ tĩnh nào khác) và không tra
                    # được giá trị -> None, giữ đúng hành vi cũ (ô trống hẳn,
                    # không phải chuỗi rỗng). Có chữ tĩnh kèm theo thì giữ
                    # nguyên phần chữ đó dù giá trị động có rỗng hay không.
                    sheet_repl[cell.coordinate] = new_v if new_v.strip() else None
            if sheet_repl:
                replacements[ws.title] = sheet_repl
    finally:
        wb.close()

    _write_patched_xlsx(template_path, output_path, replacements)
    return output_path
