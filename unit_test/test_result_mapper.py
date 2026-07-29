"""
unit_test/test_result_mapper.py
=================================
Test cấu trúc bảng A1-A8 của template QTKĐ 2.461:2018 (CNT-90XL), đặc biệt
hành vi lấy giá trị TUẦN TỰ từ StepResult(action="report_val") thay cho cơ
chế report_tag {table,row_key,field} cũ (đã bỏ vì không dùng được trong
Loop — xem unit_test/test_scenario.py::test_report_val_inside_loop_*).

report_val không mang tên bảng đích (bỏ hẳn — xem test_scenario.py) vì 1
lần chạy kịch bản luôn ứng với đúng 1 bài test/1 bảng; map_results() luôn
lấy TOÀN BỘ report_val trong step_results, không lọc theo tên bảng.
"""

from core.result_mapper import map_results, TABLE_MAPPERS, TABLE_ROW_KEYS
from core.scenario_runner import StepResult


def _push(value: float, ok: bool = True) -> StepResult:
    return StepResult(action="report_val", value=value, ok=ok)


def test_all_table_ids_registered():
    assert set(TABLE_MAPPERS.keys()) == {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"}


def test_no_report_val_returns_all_blank_rows():
    """Đúng tình trạng thật khi kịch bản chưa gắn report_val — mọi ô để
    trống, không lỗi (giống cong_suat.json trước đây với NRP2)."""
    rt = map_results("A5", [])
    assert len(rt.rows) == 11
    assert all(r.value_measured is None and r.passed is None for r in rt.rows)
    assert rt.note == ""


def test_a5_binds_values_sequentially_in_order():
    n = len(TABLE_ROW_KEYS["A5"])
    step_results = [_push(5.0 + i) for i in range(n)]
    rt = map_results("A5", step_results)
    assert len(rt.rows) == n
    for i, row in enumerate(rt.rows):
        assert row.value_measured == 5.0 + i
        assert row.error is not None   # delta_f tự tính từ freq_set của dòng đó


def test_a5_missing_values_leave_tail_blank():
    n = len(TABLE_ROW_KEYS["A5"])
    step_results = [_push(100.0 + i) for i in range(5)]   # thiếu so với 11 dòng
    rt = map_results("A5", step_results)
    assert len(rt.rows) == n
    for i, row in enumerate(rt.rows):
        if i < 5:
            assert row.value_measured == 100.0 + i
        else:
            assert row.value_measured is None
    assert rt.note == ""   # thiếu -> chỉ để trống, không cảnh báo


def test_a5_excess_values_ignored_with_note():
    n = len(TABLE_ROW_KEYS["A5"])
    step_results = [_push(1.0 + i) for i in range(n + 4)]   # dư 4 giá trị
    rt = map_results("A5", step_results)
    assert len(rt.rows) == n
    assert rt.rows[0].value_measured == 1.0
    assert rt.rows[-1].value_measured == float(n)
    assert "dư 4" in rt.note


def test_a1_consumes_all_values_into_single_row_raw_readings():
    step_results = [_push(9_999_998.0 + i) for i in range(7)]
    rt = map_results("A1", step_results)
    assert len(rt.rows) == 1
    assert len(rt.rows[0].raw_readings) == 7
    assert rt.rows[0].value_measured == sum(rt.rows[0].raw_readings) / 7
    assert rt.note == ""   # A1 luôn tiêu thụ hết mảng -> không thể dư


def test_a2_binds_mvrms_sequentially():
    n = len(TABLE_ROW_KEYS["A2"])
    step_results = [_push(1.0 + i) for i in range(n)]
    rt = map_results("A2", step_results)
    assert len(rt.rows) == n
    assert [r.value_measured for r in rt.rows] == [1.0 + i for i in range(n)]
    assert all(r.value_unit == "mVrms" for r in rt.rows)


def test_report_val_not_ok_is_ignored():
    step_results = [_push(5.0, ok=False), _push(6.0)]
    rt = map_results("A5", step_results)
    assert rt.rows[0].value_measured == 6.0


def test_unknown_table_id_returns_none():
    assert map_results("Z9", []) is None
