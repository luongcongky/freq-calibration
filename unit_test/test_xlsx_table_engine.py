"""
unit_test/test_xlsx_table_engine.py
======================================
Test core/xlsx_table_engine.py::render_xlsx_with_table_contexts() — song
song với unit_test/test_report_templates_generic.py nhưng cho mẫu Excel:
gõ text report_val('<id>')/result('<id>') vào ô, quét + ghi số liệu THÔ vào
đúng ô, giữ nguyên công thức khác trong sheet.
"""

import zipfile
from datetime import date

import openpyxl
import pytest

from core import table_engine
from core import xlsx_table_engine
from core.table_descriptor import TableDescriptor, RowDef
from core.scenario_runner import StepResult
from core.session import CalibrationSession, SessionMeta, DUTInfo, SessionTest


def _descriptor() -> TableDescriptor:
    return TableDescriptor(
        schema_version=1, table_id="T1", name="Bảng thử nghiệm", order=1,
        scenario_file="", layout="repeated_rows", value_unit="dBm",
        value_format="dbm_no_unit",
        rows=[
            RowDef(key="10 MHz", raw_count=3),
            RowDef(key="50 MHz", raw_count=1),
        ],
        columns=[], pass_rule={"type": "none"}, merge=[],
    )


def _session_with_result(descriptor: TableDescriptor) -> CalibrationSession:
    test = SessionTest(table_id="T1", name="Bảng thử nghiệm", enabled=True)
    test.step_results = [
        StepResult(action="report_val", ok=True, value=1.0),
        StepResult(action="report_val", ok=True, value=2.0),
        StepResult(action="report_val", ok=True, value=3.0),
        StepResult(action="report_val", ok=True, value=10.0),
    ]
    test.result_table = table_engine.map_table(descriptor, test.step_results)
    for r in test.result_table.rows:
        r.confirmed = True
    session = CalibrationSession(
        template_id="TEST", meta=SessionMeta(dut=DUTInfo(serial="SN1"), date=date(2026, 9, 17)),
        tests=[test],
    )
    return session


def _build_template_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A2"] = "10 MHz"
    ws["B2"] = "report_val('T1')"
    ws["C2"] = "report_val('T1')"
    ws["D2"] = "report_val('T1')"
    ws["E2"] = "=AVERAGE(B2:D2)"
    ws["A3"] = "50 MHz"
    ws["B3"] = "report_val('T1')"
    ws["F2"] = "result('T1')"
    ws["G2"] = "Nhãn tĩnh không đụng tới"
    wb.save(str(path))


def test_render_xlsx_writes_raw_values_and_keeps_formulas(tmp_path):
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    tpl_path = tmp_path / "tpl.xlsx"
    _build_template_xlsx(tpl_path)
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(session, [descriptor], tpl_path, out_path)

    wb = openpyxl.load_workbook(str(out_path), data_only=False)
    ws = wb.active

    # report_val() -> SỐ THỰC (không phải chuỗi định dạng), đúng thứ tự
    assert ws["B2"].value == 1.0
    assert ws["C2"].value == 2.0
    assert ws["D2"].value == 3.0
    assert ws["B3"].value == 10.0

    # Công thức khác giữ NGUYÊN, không bị đụng tới
    assert ws["E2"].value == "=AVERAGE(B2:D2)"
    assert ws["G2"].value == "Nhãn tĩnh không đụng tới"

    # result('T1') — pass_rule "none" -> Đạt/Không đạt rỗng (openpyxl chuẩn
    # hoá chuỗi rỗng thành None khi lưu/đọc lại, xem test dưới)
    assert ws["F2"].value is None

    # Ép Excel tự tính lại công thức khi mở file kết quả
    assert wb.calculation.fullCalcOnLoad is True


def test_render_xlsx_missing_table_id_writes_empty_result(tmp_path):
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    tpl_path = tmp_path / "tpl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "result('KHONG_TON_TAI')"
    wb.save(str(tpl_path))
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(session, [descriptor], tpl_path, out_path)

    wb2 = openpyxl.load_workbook(str(out_path))
    assert wb2.active["A1"].value is None


def test_render_xlsx_binds_header_fields_when_meta_context_fn_given(tmp_path):
    from core.generic_report_context import build_meta_context

    descriptor = _descriptor()
    session = _session_with_result(descriptor)
    session.meta.dut.name = "Cảm biến công suất"
    session.meta.dut.serial = "SN-999"
    session.meta.operator = "nguyễn văn a"

    tpl_path = tmp_path / "tpl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "header('name')"
    ws["A2"] = "header('serial')"
    ws["A3"] = "header('khong_ton_tai')"
    wb.save(str(tpl_path))
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(
        session, [descriptor], tpl_path, out_path,
        lambda s: build_meta_context(s, {"kind": "kiem_dinh"}),
    )

    wb2 = openpyxl.load_workbook(str(out_path))
    ws2 = wb2.active
    assert ws2["A1"].value == "Cảm biến công suất"
    assert ws2["A2"].value == "SN-999"
    assert ws2["A3"].value is None   # field header không tồn tại -> rỗng, không lỗi


def test_render_xlsx_header_marker_embedded_in_static_text(tmp_path):
    """Khách hàng hỏi: 1 ô ghi 'Nhiệt độ: header(...)' (nhãn + tag CHUNG 1 ô)
    thì app có link được không? -> Có, với header()/result()/gcn_*() (luôn
    là chuỗi hiển thị) — chỉ report_val() mới bắt buộc chiếm trọn ô (cần giữ
    số thực cho công thức khác tham chiếu)."""
    from core.generic_report_context import build_meta_context

    descriptor = _descriptor()
    session = _session_with_result(descriptor)
    session.meta.temperature = "23 °C"

    tpl_path = tmp_path / "tpl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Nhiệt độ: header('temperature')"
    ws["A2"] = "Trước: header('khong_ton_tai')"    # field rỗng nhưng CÓ chữ tĩnh kèm -> giữ chữ tĩnh
    ws["A3"] = "Trước header('temperature') sau"   # 2 đoạn chữ tĩnh bao quanh
    ws["A4"] = "header('khong_ton_tai')"           # CHỈ marker, không ra giá trị -> None (như cũ)
    wb.save(str(tpl_path))
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(
        session, [descriptor], tpl_path, out_path,
        lambda s: build_meta_context(s, {"kind": "kiem_dinh"}),
    )

    wb2 = openpyxl.load_workbook(str(out_path))
    ws2 = wb2.active
    assert ws2["A1"].value == "Nhiệt độ: 23 °C"
    assert ws2["A2"].value == "Trước: "
    assert ws2["A3"].value == "Trước 23 °C sau"
    assert ws2["A4"].value is None


def test_render_xlsx_report_val_requires_whole_cell_not_embedded(tmp_path):
    """report_val() nhúng trong chữ tĩnh KHÔNG được hỗ trợ (phải ghi SỐ THẬT
    để công thức khác tính tiếp, mix với chữ sẽ ép cả ô thành chuỗi) -> ô giữ
    nguyên y hệt chữ gốc, không bị thay thế/không bị lỗi."""
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    tpl_path = tmp_path / "tpl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Giá trị: report_val('T1')"
    wb.save(str(tpl_path))
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(session, [descriptor], tpl_path, out_path)

    wb2 = openpyxl.load_workbook(str(out_path))
    assert wb2.active["A1"].value == "Giá trị: report_val('T1')"


def test_render_xlsx_header_marker_stays_untouched_without_meta_context_fn(tmp_path):
    """Mẫu cũ không có ô header('...') nào, hoặc gọi không truyền
    meta_context_fn -> tương thích ngược, không crash, ô header('...') (nếu
    có) chỉ đơn giản bị xoá rỗng như mọi field không tìm thấy."""
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    tpl_path = tmp_path / "tpl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "header('name')"
    wb.save(str(tpl_path))
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(session, [descriptor], tpl_path, out_path)

    wb2 = openpyxl.load_workbook(str(out_path))
    assert wb2.active["A1"].value is None


def test_build_raw_rows_by_table_returns_raw_readings(tmp_path):
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    raw_by_table = table_engine.build_raw_rows_by_table(session, [descriptor])
    assert list(raw_by_table.keys()) == ["T1"]
    rows = raw_by_table["T1"]
    assert [r.raw_readings for r in rows] == [[1.0, 2.0, 3.0], [10.0]]


def _inject_fake_header_logo(xlsx_path):
    """Giả lập 1 file mẫu THẬT có logo/đường kẻ chữ ký trong header trang
    (ảnh gắn qua VML legacy drawing, như khách hàng mô tả ở báo cáo lỗi #1/
    #2) — chỉ cần đủ cấu trúc zip để kiểm tra các phần này còn NGUYÊN VẸN
    sau khi render, không cần đúng 100% schema VML (app không mở lại file
    bằng Excel trong test)."""
    with zipfile.ZipFile(str(xlsx_path), "r") as z:
        names = {n: z.read(n) for n in z.namelist()}

    sheet_xml = names["xl/worksheets/sheet1.xml"].decode("utf-8")
    assert "</worksheet>" in sheet_xml
    if "xmlns:r=" not in sheet_xml.split(">", 1)[0]:
        sheet_xml = sheet_xml.replace(
            "<worksheet ",
            '<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ',
            1,
        )
    sheet_xml = sheet_xml.replace(
        "</worksheet>",
        "<headerFooter><oddHeader>&amp;G</oddHeader></headerFooter>"
        '<legacyDrawingHF r:id="rId100"/></worksheet>',
    )
    names["xl/worksheets/sheet1.xml"] = sheet_xml.encode("utf-8")
    names["xl/worksheets/_rels/sheet1.xml.rels"] = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId100" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" '
        b'Target="../drawings/vmlDrawing1.vml"/></Relationships>'
    )
    names["xl/drawings/vmlDrawing1.vml"] = b"<xml>FAKE VML LOGO + SIGNATURE LINE</xml>"
    names["xl/media/image1.png"] = b"FAKE-LOGO-PNG-BYTES-NOT-A-REAL-IMAGE"

    with zipfile.ZipFile(str(xlsx_path), "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in names.items():
            z.writestr(name, data)


def test_render_xlsx_preserves_header_logo_and_other_zip_parts_untouched(tmp_path):
    """Lỗi khách báo: logo/textbox/đường kẻ chữ ký trong HEADER trang bị mất
    sau khi xuất, dù đã cài Pillow (openpyxl không giữ được VML legacy
    drawing khi ghi lại) — render_xlsx_with_table_contexts không còn
    wb.save() nữa nên các phần này phải còn NGUYÊN VẸN (byte-for-byte)."""
    descriptor = _descriptor()
    session = _session_with_result(descriptor)

    tpl_path = tmp_path / "tpl.xlsx"
    _build_template_xlsx(tpl_path)
    _inject_fake_header_logo(tpl_path)
    out_path = tmp_path / "out.xlsx"

    xlsx_table_engine.render_xlsx_with_table_contexts(session, [descriptor], tpl_path, out_path)

    with zipfile.ZipFile(str(tpl_path)) as src, zipfile.ZipFile(str(out_path)) as dst:
        for name in ("xl/drawings/vmlDrawing1.vml", "xl/media/image1.png",
                      "xl/worksheets/_rels/sheet1.xml.rels"):
            assert dst.read(name) == src.read(name)

        out_sheet_xml = dst.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "<headerFooter><oddHeader>&amp;G</oddHeader></headerFooter>" in out_sheet_xml
        assert '<legacyDrawingHF r:id="rId100"/>' in out_sheet_xml

    # Giá trị vẫn được ghi đúng như test gốc — không vì vá XML tay mà hỏng
    # phần thay dữ liệu.
    wb = openpyxl.load_workbook(str(out_path), data_only=False)
    ws = wb.active
    assert ws["B2"].value == 1.0
    assert ws["E2"].value == "=AVERAGE(B2:D2)"
