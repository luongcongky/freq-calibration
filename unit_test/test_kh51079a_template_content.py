"""
unit_test/test_kh51079a_template_content.py
==============================================
N-01 (test_reports/2026-10-09_khong_thiet_bi_retest/BAO_CAO_TEST_LAI_K01_K12.md)
— lỗi NỘI DUNG trong chính file mẫu Excel THẬT
templates/KH_51079A_XLSX/bienban.xlsx (không phải code Python): ô B15
("Kết luận (chọn):") gõ CỨNG chữ "Đạt", không lấy từ ô Kết luận của app —
biên bản luôn ra "Kết luận (chọn): Đạt" dù mọi bài đo đều LỖI/chưa có số
liệu nào (sau khi K08 đã sửa app để ô Kết luận để TRỐNG trong trường hợp
đó). Sửa: B15 đổi sang marker header('conclusion') — đúng quy ước
core/xlsx_table_engine.py đã dùng cho B17/E17 trong CÙNG file.
"""

from datetime import date

import pytest

from core.session import CalibrationSession
from core.report_templates import get_template

pytest.importorskip("openpyxl")
import openpyxl


def _render(tmp_path, conclusion: str):
    session = CalibrationSession(template_id="KH_51079A_XLSX")
    session.meta.date = date(2026, 10, 9)
    session.meta.conclusion = conclusion
    tpl = get_template("KH_51079A_XLSX")
    out = tpl.generate_bienban(session, str(tmp_path / "bienban.xlsx"))
    return openpyxl.load_workbook(out)


def test_template_source_no_longer_hardcodes_dat():
    """File mẫu THẬT trên đĩa không còn gõ cứng 'Đạt' ở B15."""
    wb = openpyxl.load_workbook("templates/KH_51079A_XLSX/bienban.xlsx")
    ws = wb["Thông tin chung"]
    assert ws["B15"].value != "Đạt", (
        "templates/KH_51079A_XLSX/bienban.xlsx vẫn gõ cứng 'Đạt' ở B15 (N-01)")
    assert "header(" in str(ws["B15"].value), (
        f"B15 không dùng marker header(...) như B17/E17 cùng file: {ws['B15'].value!r}")


def test_rendered_conclusion_blank_when_session_conclusion_empty(tmp_path):
    """Mọi bài LỖI, chưa có số liệu -> app để trống ô Kết luận (K08) -> biên
    bản xuất ra KHÔNG được tự ghi 'Đạt' (N-01)."""
    wb = _render(tmp_path, conclusion="")
    ws = wb["Thông tin chung"]
    assert ws["B15"].value in (None, ""), (
        f"Biên bản vẫn ghi kết luận dù app để trống (N-01): {ws['B15'].value!r}")


def test_rendered_conclusion_matches_session_when_set(tmp_path):
    """Không được vô tình đổi hành vi khi THỰC SỰ có kết luận."""
    wb = _render(tmp_path, conclusion="Đạt yêu cầu kỹ thuật đo lường")
    ws = wb["Thông tin chung"]
    assert ws["B15"].value == "Đạt yêu cầu kỹ thuật đo lường"
