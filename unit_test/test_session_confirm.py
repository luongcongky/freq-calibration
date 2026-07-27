"""
unit_test/test_session_confirm.py
==================================
Test cơ chế xác nhận từng dòng kết quả (TableRow.confirmed) trước khi tính
vào ReportTable/CalibrationSession — vòng lặp lưu/nạp JSON và tính đạt/không.
"""

import json

from core.session import CalibrationSession, SessionTest, ReportTable, TableRow


def _row(key, passed, confirmed):
    return TableRow(key=key, value_measured=1.0, value_unit="Hz",
                    passed=passed, confirmed=confirmed)


# ---------------------------------------------------------------------------
# ReportTable.confirmed_rows / confirmed_passed
# ---------------------------------------------------------------------------

def test_confirmed_rows_filters_unconfirmed():
    rt = ReportTable(table_id="A5", name="x", rows=[
        _row("5Hz", True, confirmed=True),
        _row("10Hz", False, confirmed=False),
    ])
    confirmed = rt.confirmed_rows()
    assert [r.key for r in confirmed] == ["5Hz"]


def test_confirmed_passed_none_when_nothing_confirmed():
    rt = ReportTable(table_id="A5", name="x", rows=[_row("5Hz", True, confirmed=False)])
    assert rt.confirmed_passed is None


def test_confirmed_passed_none_for_calibration_style_rows():
    """Bảng kiểu 'hiệu chuẩn' (vd QTHC 2.515 NRP2): mọi dòng passed=None dù
    đã xác nhận -> không được kết luận nhầm 'ĐẠT' (all([]) == True trong
    Python là cái bẫy đã sửa)."""
    rt = ReportTable(table_id="A2", name="x", rows=[
        _row("10MHz", None, confirmed=True),
        _row("50MHz", None, confirmed=True),
    ])
    assert rt.confirmed_passed is None


def test_confirmed_passed_true_when_all_confirmed_pass():
    rt = ReportTable(table_id="A5", name="x", rows=[
        _row("5Hz", True, confirmed=True),
        _row("10Hz", True, confirmed=True),
        _row("100Hz", False, confirmed=False),  # không xác nhận -> không tính
    ])
    assert rt.confirmed_passed is True


def test_confirmed_passed_false_when_a_confirmed_row_fails():
    rt = ReportTable(table_id="A5", name="x", rows=[
        _row("5Hz", True, confirmed=True),
        _row("10Hz", False, confirmed=True),
    ])
    assert rt.confirmed_passed is False


# ---------------------------------------------------------------------------
# CalibrationSession.all_passed
# ---------------------------------------------------------------------------

def _session_with(rows_by_test):
    session = CalibrationSession()
    for table_id, rows in rows_by_test.items():
        rt = ReportTable(table_id=table_id, name=table_id, rows=rows)
        session.tests.append(SessionTest(table_id=table_id, name=table_id, enabled=True,
                                         status="done", result_table=rt))
    return session


def test_all_passed_none_when_no_test_has_confirmed_rows():
    session = _session_with({"A1": [_row("10MHz", True, confirmed=False)]})
    assert session.all_passed is None


def test_all_passed_true_when_all_confirmed_rows_pass():
    session = _session_with({
        "A1": [_row("10MHz", True, confirmed=True)],
        "A5": [_row("5Hz", True, confirmed=True)],
    })
    assert session.all_passed is True


def test_all_passed_false_when_one_test_has_failing_confirmed_row():
    session = _session_with({
        "A1": [_row("10MHz", True, confirmed=True)],
        "A5": [_row("5Hz", False, confirmed=True)],
    })
    assert session.all_passed is False


def test_all_passed_ignores_disabled_tests():
    session = _session_with({"A5": [_row("5Hz", False, confirmed=True)]})
    session.tests[0].enabled = False
    assert session.all_passed is None


# ---------------------------------------------------------------------------
# Vòng lặp lưu/nạp JSON giữ nguyên confirmed
# ---------------------------------------------------------------------------

def test_save_load_json_preserves_confirmed(tmp_path):
    session = _session_with({
        "A2": [_row("100kHz", True, confirmed=True), _row("1MHz", True, confirmed=False)],
    })
    path = tmp_path / "session.json"
    session.save_json(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["tests"][0]["result_table"]["rows"][0]["confirmed"] is True
    assert raw["tests"][0]["result_table"]["rows"][1]["confirmed"] is False

    loaded = CalibrationSession.load_json(path)
    rows = loaded.tests[0].result_table.rows
    assert rows[0].confirmed is True
    assert rows[1].confirmed is False
    assert loaded.tests[0].result_table.confirmed_passed is True
