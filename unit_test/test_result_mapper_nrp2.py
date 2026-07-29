"""
unit_test/test_result_mapper_nrp2.py
======================================
Test cấu trúc bảng A1/A2/A3 của template QTHC 2.515:2021 (NRP2) và hành vi
khi kịch bản không đẩy report_val nào (đúng tình trạng thật của
scenarios/nrp2/cong_suat.json — mọi ô kết quả phải để trống, không lỗi).
"""

from core.result_mapper_nrp2 import map_results_nrp2, TABLE_MAPPERS_NRP2
from core.report_templates import list_templates, get_template
from core.report_templates.qthc_2515_nrp2 import QTHC2515NRP2Template
from core.scenario_runner import StepResult


def _push(value: float) -> StepResult:
    return StepResult(action="report_val", value=value, ok=True)


def test_table_a1_has_one_row():
    rt = map_results_nrp2("A1", [])
    assert rt.table_id == "A1"
    assert len(rt.rows) == 1
    assert rt.rows[0].value_measured is None
    assert rt.rows[0].passed is None


def test_table_a2_has_13_rows():
    rt = map_results_nrp2("A2", [])
    assert len(rt.rows) == 13
    assert all(r.value_measured is None and r.passed is None for r in rt.rows)
    assert rt.rows[0].key == "10MHz"
    assert rt.rows[-1].key == "49GHz"


def test_table_a3_has_48_rows():
    rt = map_results_nrp2("A3", [])
    assert len(rt.rows) == 48
    # 8 tần số x 6 mức công suất
    freqs = {r.freq_set for r in rt.rows}
    assert len(freqs) == 8


def test_a1_consumes_exactly_10_fixed_readings():
    step_results = [_push(1e-3 + i * 1e-6) for i in range(10)]
    rt = map_results_nrp2("A1", step_results)
    assert len(rt.rows) == 1
    assert len(rt.rows[0].raw_readings) == 10
    assert rt.rows[0].value_measured == sum(rt.rows[0].raw_readings) / 10
    assert rt.note == ""


def test_a1_extra_beyond_10_reported_as_note():
    step_results = [_push(1e-3) for _ in range(13)]
    rt = map_results_nrp2("A1", step_results)
    assert len(rt.rows[0].raw_readings) == 10
    assert "dư 3" in rt.note


def test_a2_binds_5_raw_readings_per_row_in_order():
    n_rows = 13
    step_results = []
    for row_i in range(n_rows):
        step_results.extend(_push(row_i + k * 0.01) for k in range(5))
    rt = map_results_nrp2("A2", step_results)
    assert len(rt.rows) == n_rows
    for row_i, row in enumerate(rt.rows):
        assert len(row.raw_readings) == 5
        assert row.raw_readings[0] == row_i
        assert row.value_measured == sum(row.raw_readings) / 5


def test_a2_partial_last_row_gets_fewer_raw_readings():
    step_results = [_push(0.0) for _ in range(5 * 12 + 2)]   # thiếu 3 giá trị cho dòng cuối
    rt = map_results_nrp2("A2", step_results)
    assert len(rt.rows) == 13
    assert len(rt.rows[11].raw_readings) == 5
    assert len(rt.rows[12].raw_readings) == 2
    assert rt.note == ""


def test_unknown_table_id_returns_none():
    assert map_results_nrp2("Z9", []) is None


def test_all_table_ids_registered():
    assert set(TABLE_MAPPERS_NRP2.keys()) == {"A1", "A2", "A3"}


# ---------------------------------------------------------------------------
# Template registration
# ---------------------------------------------------------------------------

def test_template_registered_in_list():
    ids = dict(list_templates())
    assert "QTHC_2515_NRP2" in ids
    assert "NRP2" in ids["QTHC_2515_NRP2"]


def test_template_default_tests_structure():
    tpl = get_template("QTHC_2515_NRP2")
    tests = tpl.default_tests()
    assert [t.table_id for t in tests] == ["A1", "A2", "A3"]
    # A1/A3 chưa có kịch bản thật -> để trống cho người dùng tự bổ sung
    assert tests[0].scenario_path == ""
    assert tests[2].scenario_path == ""
    # A2 trỏ đúng bản sao nguyên văn cong_suat.json
    assert tests[1].scenario_path.endswith("cong_suat.json")


def test_template_is_isinstance():
    tpl = get_template("QTHC_2515_NRP2")
    assert isinstance(tpl, QTHC2515NRP2Template)
