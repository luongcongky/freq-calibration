"""
unit_test/test_report_preview_freq_power.py
==============================================
Khoá lại yêu cầu: bảng ở Bước 2/Bước 3 phải khớp ĐÚNG cấu trúc file docx
thật (tiêu đề cột, số dòng/cột, gộp ô tĩnh) — không phải bảng rà soát
chung. Tiêu đề cột lấy chung từ core/table_layouts.py (cùng nguồn
scripts/build_generic_seed_templates.py dùng để dựng file .docx) nên 2 nơi
không thể lệch nhau; test này chỉ xác nhận builder GUI dựng đúng SỐ DÒNG/
CỘT + đặt đúng giá trị report_val() vào đúng ô theo cùng layout đó.
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.report_templates import get_template  # noqa: E402
from core.scenario_runner import StepResult  # noqa: E402
from core import table_layouts as lay  # noqa: E402
from gui.report_preview import build_wysiwyg_table  # noqa: E402

FREQ_ID = "TEMPLATE_FREQ"
POWER_ID = "TEMPLATE_POWER"


def _run(template_id: str, table_id: str, values: list):
    tpl = get_template(template_id)
    tests = {t.table_id: t for t in tpl.default_tests()}
    test = tests[table_id]
    test.step_results = [StepResult(action="report_val", value=v, ok=True) for v in values]
    test.result_table = tpl.map_test_result(test)
    for r in test.result_table.rows:
        r.confirmed = True
    return test.result_table.rows


def _headers(tbl) -> list:
    return [tbl.horizontalHeaderItem(c).text() for c in range(tbl.columnCount())]


def test_freq_a1_matches_docx_layout():
    fci = [10_000_000.0 + i for i in range(5)]
    rows = _run(FREQ_ID, "A1", fci + [10_000_000.2, 2e-8])
    tbl = build_wysiwyg_table(FREQ_ID, "A1", rows, measured_counts=[5])
    assert _headers(tbl) == lay.FREQ_A1_HEADERS
    assert tbl.rowCount() == 6   # 5 fCi + 1 dòng fC/δf riêng — khớp docx
    assert tbl.item(0, 1).text() == "10000000 Hz"
    assert tbl.item(4, 1).text() == "10000004 Hz"
    assert tbl.item(0, 2) is None   # fC chỉ ở dòng cuối, không lặp lại
    assert "10000000" in tbl.item(5, 2).text()
    assert tbl.item(5, 4).text() == "± 2,4×10⁻⁷"


def test_freq_a2_matches_docx_layout():
    rows = _run(FREQ_ID, "A2", [12.0] * 12)
    tbl = build_wysiwyg_table(FREQ_ID, "A2", rows)
    assert _headers(tbl) == lay.FREQ_SENSITIVITY_HEADERS
    assert tbl.rowCount() == 12
    assert tbl.item(0, 0).text() == "100 kHz"
    assert tbl.item(0, 2).text() == "≤ 15 mVrms"
    assert tbl.item(9, 2).text() == "≤ 25 mVrms"


def test_freq_a5_matches_docx_layout_with_2_report_val_per_row():
    values = []
    for i in range(11):
        values += [5.0 + i, 1.2e-8]
    rows = _run(FREQ_ID, "A5", values)
    tbl = build_wysiwyg_table(FREQ_ID, "A5", rows, measured_counts=[1] * 11)
    assert _headers(tbl) == lay.freq_error_headers("A")
    assert tbl.rowCount() == 11
    assert tbl.item(0, 1).text() == "5 Hz"       # giá trị đo (slot 1)
    assert "1,2e-08" in tbl.item(0, 2).text()      # sai số (slot 2)
    assert tbl.item(0, 3).text() == "± 2,4×10⁻⁷"


def test_freq_a8_matches_docx_layout():
    values = []
    for i in range(13):
        values += [0.2 + i * 1e-6, 1e-8]
    rows = _run(FREQ_ID, "A8", values)
    tbl = build_wysiwyg_table(FREQ_ID, "A8", rows, measured_counts=[1] * 13)
    assert _headers(tbl) == lay.FREQ_A8_HEADERS
    assert tbl.item(0, 0).text() == "5 Hz (200 ms)"


def test_power_a1_matches_docx_layout():
    """10 lần đo (measured_count) + 2 field kịch bản tự tính (TB, Độ KĐBĐ)
    = 12 report_val — chia 2 nhóm 5 cột + 1 dòng Trung Bình riêng, khớp
    scripts/build_generic_seed_templates.py."""
    rows = _run(POWER_ID, "A1", [0.001] * 10 + [0.001, 0.00005])
    tbl = build_wysiwyg_table(POWER_ID, "A1", rows, measured_counts=[10])
    assert _headers(tbl) == lay.power_a1_headers(5)
    assert tbl.rowCount() == 3   # 2 nhóm 5 lần đo + 1 dòng Trung Bình
    assert tbl.item(0, 0).text() == "1 mW"
    assert tbl.item(1, 0).text() == "1 mW"
    # Dòng Trung Bình: TB ở cột "lần 1" (đầu khối), Độ KĐBĐ ở ĐÚNG cột
    # header "Độ KĐBĐ" (cột cuối) — không lẫn vào cột "lần 2".
    assert tbl.item(2, 1).text() != ""
    assert tbl.item(2, 2) is None
    assert tbl.item(2, 6).text() != ""
    assert tbl.item(2, 0).text() == "Trung Bình"
    assert tbl.item(0, 5).text() == "0,001 W"


def test_power_a2_matches_docx_layout():
    values = []
    for _ in range(13):
        values += [1.0] * 5 + [1.0, 0.05]
    rows = _run(POWER_ID, "A2", values)
    tbl = build_wysiwyg_table(POWER_ID, "A2", rows, measured_counts=[5] * 13)
    assert _headers(tbl) == lay.power_a2_headers(5)
    assert tbl.rowCount() == 13
    assert tbl.item(0, 0).text() == "10 MHz"


def test_power_a3_matches_docx_layout_and_merges_freq_group():
    values = []
    for _ in range(48):
        values += [-30.0] * 5 + [-30.0, 0.5]
    rows = _run(POWER_ID, "A3", values)
    tbl = build_wysiwyg_table(POWER_ID, "A3", rows, measured_counts=[5] * 48)
    assert _headers(tbl) == lay.power_a3_headers(5)
    assert tbl.rowCount() == 48
    assert tbl.item(0, 1).text() == "-30,00 dBm"
    same_group = tbl.item(1, 0) is None   # gộp với dòng 0 (cùng tần số 50MHz)
    assert same_group
