"""
unit_test/test_table_engine.py
=================================
Test core/table_engine.py::build_cursor_context.

BIÊN BẢN (bản ghi thô) — CHỈ `report_val()`: 1 mảng duy nhất, đọc phẳng từ
raw_readings của từng dòng đã xác nhận theo đúng thứ tự trái→phải, trên→
dưới — mọi giá trị đều do kịch bản/người dùng tự tính rồi tự đẩy, phần mềm
KHÔNG được tự suy ra field nào khác trong Biên Bản.

GCN (văn bản tổng hợp/kết luận) — được phép có field phần mềm tự tổng hợp
lại từ dữ liệu report_val Biên Bản ĐÃ CÓ SẴN (không cần sửa kịch bản):
  - `result` — Đạt/Không đạt NGƯỜI DÙNG tự chọn ở Bước 2, không phải công
    thức tự động.
  - `gcn_avg()`/`gcn_error()`/`gcn_limit()` — trung bình/sai số (số hiệu
    chỉnh)/ngưỡng, tính lại từ TableRow.value_measured/error/limit mà
    map_table() đã tính sẵn theo đúng pass_rule của bảng.
"""

from core import table_engine
from core.session import CalibrationSession, ReportTable, SessionTest, TableRow
from core.table_descriptor import RowDef, TableDescriptor


def _descriptor(**overrides) -> TableDescriptor:
    kwargs = dict(schema_version=1, table_id="A9", name="Bảng thử", order=1,
                   rows=[RowDef(key="row1")], value_format="text")
    kwargs.update(overrides)
    return TableDescriptor(**kwargs)


def _row(**overrides) -> TableRow:
    kwargs = dict(key="r", raw_readings=[12.3], confirmed=True)
    kwargs.update(overrides)
    return TableRow(**kwargs)


def test_report_val_sequential_matches_document_order():
    """Mỗi dòng 1 report_val (raw_readings=[x]) -> gọi report_val() N lần
    trả đúng N giá trị theo đúng thứ tự dòng, KHÔNG phải theo value_measured."""
    rows = [_row(raw_readings=[1.0]), _row(raw_readings=[2.0]), _row(raw_readings=[3.0])]
    descriptor = _descriptor(rows=[RowDef(key="r0"), RowDef(key="r1"), RowDef(key="r2")])
    ctx = table_engine.build_cursor_context(descriptor, rows, rt=None)
    assert ctx["report_val"]() == table_engine._format("text", 1.0)
    assert ctx["report_val"]() == table_engine._format("text", 2.0)
    assert ctx["report_val"]() == table_engine._format("text", 3.0)


def test_report_val_flattens_multiple_values_per_row_in_order():
    """1 dòng có NHIỀU giá trị (vd giá trị đo + sai số kịch bản tự tính rồi
    đẩy cùng lúc) -> report_val() đọc phẳng đúng thứ tự trong dòng trước,
    rồi mới sang dòng kế — khớp đúng thứ tự trái->phải, trên->dưới thật sự
    của tài liệu (không phải 1 giá trị đại diện/dòng)."""
    rows = [_row(raw_readings=[1.0, 2.0]), _row(raw_readings=[3.0])]
    descriptor = _descriptor(rows=[RowDef(key="r0"), RowDef(key="r1")])
    ctx = table_engine.build_cursor_context(descriptor, rows, rt=None)
    assert ctx["report_val"]() == table_engine._format("text", 1.0)
    assert ctx["report_val"]() == table_engine._format("text", 2.0)
    assert ctx["report_val"]() == table_engine._format("text", 3.0)


def test_report_val_uses_descriptor_value_format():
    rows = [_row(raw_readings=[1000000.0])]
    ctx = table_engine.build_cursor_context(_descriptor(value_format="freq"), rows, rt=None)
    assert ctx["report_val"]() == table_engine._format("freq", 1000000.0)


def test_report_val_uses_per_row_value_format_seq_when_set():
    """1 dòng đẩy 2 report_val khác nghĩa (giá trị đo rồi đến sai số kịch
    bản tự tính sẵn) -> mỗi report_val() dùng ĐÚNG format khai báo cho vị
    trí đó (row_def.value_format_seq), không dùng chung 1 format cho cả
    bảng như mặc định."""
    row_def = RowDef(key="r0", raw_count=2, measured_count=1,
                      value_format_seq=["freq", "sci"])
    descriptor = _descriptor(rows=[row_def], value_format="text")
    rows = [_row(raw_readings=[1000000.0, 2.4e-7])]
    ctx = table_engine.build_cursor_context(descriptor, rows, rt=None)
    assert ctx["report_val"]() == table_engine._format("freq", 1000000.0)
    assert ctx["report_val"]() == table_engine._format("sci", 2.4e-7)


def test_cursor_exhausted_returns_blank_not_error():
    rows = [_row(raw_readings=[1.0])]
    ctx = table_engine.build_cursor_context(_descriptor(), rows, rt=None)
    ctx["report_val"]()
    assert ctx["report_val"]() == ""
    assert ctx["report_val"]() == ""


def test_only_bienban_and_gcn_summary_keys_exposed():
    """Biên Bản CHỈ có report_val (bản ghi thô) — không còn report_error/
    report_raw/report_freq/report_limit/report_passed kiểu cũ. GCN được
    phép có thêm 3 field tổng hợp (result/gcn_avg/gcn_error/gcn_limit),
    tính lại từ dữ liệu report_val Biên Bản đã có — không cần sửa kịch bản."""
    ctx = table_engine.build_cursor_context(_descriptor(), [_row()], rt=None)
    assert set(ctx.keys()) == {"report_val", "result", "gcn_avg", "gcn_error", "gcn_limit"}


def test_gcn_avg_error_limit_read_from_already_computed_row_fields():
    """gcn_avg/gcn_error/gcn_limit KHÔNG đọc raw_readings (khác report_val)
    — đọc value_measured/error/limit, tức dữ liệu map_table() đã tính sẵn
    từ CHÍNH report_val Biên Bản, không cần thêm gì từ kịch bản."""
    rows = [
        _row(raw_readings=[1.0, 2.0], value_measured=1.5, error=0.001, limit="≤ 15 mVrms"),
        _row(raw_readings=[3.0], value_measured=3.0, error=0.002, limit="≤ 25 mVrms"),
    ]
    ctx = table_engine.build_cursor_context(_descriptor(value_format="mv"), rows, rt=None)
    assert ctx["gcn_avg"]() == table_engine._format("mv", 1.5)
    assert ctx["gcn_avg"]() == table_engine._format("mv", 3.0)
    assert ctx["gcn_error"]() == table_engine._format("sci", 0.001)
    assert ctx["gcn_limit"]() == "≤ 15 mVrms"
    assert ctx["gcn_limit"]() == "≤ 25 mVrms"


def test_gcn_error_format_auto_derives_from_value_format():
    """Bảng kiểu hiệu chuẩn (value_format=dbm/w) hiện 'Số hiệu chỉnh' bằng
    correction_db/correction_mw (giá trị tự mang dấu), KHÔNG phải 'sci'
    (chỉ đúng cho sai số tương đối kiểu kiểm định)."""
    rows = [_row(error=-0.003)]
    ctx_dbm = table_engine.build_cursor_context(_descriptor(value_format="dbm"), rows, rt=None)
    assert ctx_dbm["gcn_error"]() == table_engine._format("correction_db", -0.003)

    rows = [_row(error=-0.003)]
    ctx_w = table_engine.build_cursor_context(_descriptor(value_format="w"), rows, rt=None)
    assert ctx_w["gcn_error"]() == table_engine._format("correction_mw", -0.003)

    rows = [_row(error=-0.003)]
    ctx_other = table_engine.build_cursor_context(_descriptor(value_format="hz_measured"), rows, rt=None)
    assert ctx_other["gcn_error"]() == table_engine._format("sci", -0.003)


def test_result_true_false_none_cases():
    """result lấy từ TableRow.passed do NGƯỜI DÙNG tự chọn tay ở Bước 2
    (cột Đạt/Không đạt), không phải công thức pass_rule tự động."""
    rt_true = ReportTable(table_id="A9", rows=[_row(passed=True)])
    rt_false = ReportTable(table_id="A9", rows=[_row(passed=False)])
    rt_none = ReportTable(table_id="A9", rows=[])
    d = _descriptor()
    assert table_engine.build_cursor_context(d, rt_true.confirmed_rows(), rt_true)["result"] == "Đạt"
    assert table_engine.build_cursor_context(d, rt_false.confirmed_rows(), rt_false)["result"] == "Không đạt"
    assert table_engine.build_cursor_context(d, rt_none.confirmed_rows(), rt_none)["result"] == ""


def test_result_blank_when_rt_is_none():
    ctx = table_engine.build_cursor_context(_descriptor(), [], rt=None)
    assert ctx["result"] == ""


# ---------------------------------------------------------------------------
# result — ngoại lệ "Xuất value trong GCN" (đánh dấu tay 1 ô giá trị đo ở
# Bước 2, xem gui/report_preview.py::_make_gcn_markable): thay Đạt/Không đạt
# bằng ĐÚNG giá trị đo của dòng đã đánh dấu.
# ---------------------------------------------------------------------------

def test_result_uses_marked_row_value_instead_of_pass_mark():
    row = _row(raw_readings=[12.3], confirmed=True, passed=True, gcn_export_field="raw:0")
    rt = ReportTable(table_id="A9", rows=[row])
    d = _descriptor(value_format="mv")
    ctx = table_engine.build_cursor_context(d, rt.confirmed_rows(), rt)
    assert ctx["result"] == table_engine._format("mv", 12.3)


def test_result_falls_back_to_pass_mark_when_no_row_marked():
    row = _row(raw_readings=[12.3], confirmed=True, passed=True, gcn_export_field=None)
    rt = ReportTable(table_id="A9", rows=[row])
    ctx = table_engine.build_cursor_context(_descriptor(), rt.confirmed_rows(), rt)
    assert ctx["result"] == "Đạt"


def test_result_ignores_mark_on_unconfirmed_row():
    """Dòng đánh dấu nhưng CHƯA xác nhận -> bỏ qua, result quay lại theo
    Đạt/Không đạt như bình thường."""
    row = _row(raw_readings=[12.3], confirmed=False, gcn_export_field="raw:0")
    rt = ReportTable(table_id="A9", rows=[row])
    ctx = table_engine.build_cursor_context(_descriptor(), rt.confirmed_rows(), rt)
    assert ctx["result"] == ""


def test_result_uses_row_specific_value_format_seq():
    """Dòng có value_format_seq riêng (khác value_format mặc định của bảng)
    -> phải dùng ĐÚNG format của chính dòng đó, không phải mặc định bảng."""
    row_def = RowDef(key="row1", value_format_seq=["dbm"])
    row = _row(raw_readings=[-12.345], confirmed=True, gcn_export_field="raw:0")
    rt = ReportTable(table_id="A9", rows=[row])
    d = _descriptor(rows=[row_def], value_format="text")
    ctx = table_engine.build_cursor_context(d, rt.confirmed_rows(), rt)
    assert ctx["result"] == table_engine._format("dbm", -12.345)


def test_gcn_export_value_str_none_when_index_out_of_range():
    row = _row(raw_readings=[1.0], confirmed=True, gcn_export_field="raw:5")
    rt = ReportTable(table_id="A9", rows=[row])
    assert table_engine._gcn_export_value_str(_descriptor(), rt) is None


def test_gcn_export_value_str_none_when_rt_is_none():
    assert table_engine._gcn_export_value_str(_descriptor(), None) is None


def test_build_all_table_contexts_merges_cursor_fields_without_breaking_old_keys():
    """Descriptor kiểu CŨ (không set value_format, giữ columns=[]) vẫn phải
    có cả field CŨ (rows/enabled) LẪN field MỚI (report_val/result)."""
    descriptor = _descriptor()
    row = _row(raw_readings=[42.0])
    rt = ReportTable(table_id="A9", name="Bảng thử", rows=[row])
    session = CalibrationSession()
    session.tests = [SessionTest(table_id="A9", name="Bảng thử", enabled=True, result_table=rt)]

    ctx_all = table_engine.build_all_table_contexts(session, [descriptor])
    ctx = ctx_all["A9"]

    assert ctx["enabled"] is True
    assert len(ctx["rows"]) == 1
    assert callable(ctx["report_val"])
    assert ctx["report_val"]() == table_engine._format("text", 42.0)


def test_build_all_table_contexts_fresh_cursor_each_call():
    """Mỗi lần gọi build_all_table_contexts phải tạo iterator MỚI — không
    rò rỉ state giữa 2 lần render (vd Biên Bản rồi GCN)."""
    descriptor = _descriptor()
    row = _row(raw_readings=[7.0])
    rt = ReportTable(table_id="A9", rows=[row])
    session = CalibrationSession()
    session.tests = [SessionTest(table_id="A9", enabled=True, result_table=rt)]

    ctx1 = table_engine.build_all_table_contexts(session, [descriptor])["A9"]
    assert ctx1["report_val"]() == table_engine._format("text", 7.0)

    ctx2 = table_engine.build_all_table_contexts(session, [descriptor])["A9"]
    assert ctx2["report_val"]() == table_engine._format("text", 7.0)


# ---------------------------------------------------------------------------
# map_table() — nhóm report_val theo dòng (raw_count) + raw_readings LUÔN
# lưu nguyên chunk đã tiêu thụ (kể cả raw_count=1) để report_val() cursor có
# nguồn đồng nhất. Công thức pass_rule/reference (Đạt/Không đạt tự động) vẫn
# giữ nguyên cho nội bộ/tương lai — KHÔNG dùng để hiện giá trị trong bảng
# chi tiết nữa (đó là việc của report_val), chỉ còn ý nghĩa nếu 1 template
# tự chọn dùng nó cho mục đích riêng.
# ---------------------------------------------------------------------------

def _step_results(*values):
    from core.scenario_runner import StepResult
    return [StepResult(action="report_val", value=v, ok=True) for v in values]


def test_map_table_raw_readings_always_populated_even_raw_count_one():
    d = _descriptor(rows=[RowDef(key="r1", raw_count=1), RowDef(key="r2", raw_count=1)],
                     pass_rule={"type": "none"})
    rt = table_engine.map_table(d, _step_results(1.0, 2.0))
    assert rt.rows[0].raw_readings == [1.0]
    assert rt.rows[1].raw_readings == [2.0]


def test_map_table_raw_readings_groups_multiple_values_per_row():
    """1 dòng cần hiện NHIỀU giá trị (vd giá trị đo + sai số kịch bản tự
    tính) -> raw_count=2, raw_readings giữ ĐÚNG cả 2 giá trị theo thứ tự đẩy,
    KHÔNG bị gộp/trung bình thành 1 số."""
    d = _descriptor(rows=[RowDef(key="r1", raw_count=2)], pass_rule={"type": "none"})
    rt = table_engine.map_table(d, _step_results(5.0, 0.001))
    assert rt.rows[0].raw_readings == [5.0, 0.001]


def test_map_table_relative_error_vs_fixed_limit_pass_and_fail():
    d = _descriptor(rows=[
        RowDef(key="f1", freq_set=1e6, reference=1e6, raw_count=1),
        RowDef(key="f2", freq_set=2e6, reference=2e6, raw_count=1),
    ], pass_rule={"type": "relative_error_vs_fixed_limit",
                  "params": {"fixed_limit": 2.4e-7, "limit_str": "± 2,4×10⁻⁷"}})
    rt = table_engine.map_table(d, _step_results(1_000_000.1, 2_000_010.0))
    assert rt.rows[0].passed is True    # 0.1/1e6 = 1e-7 <= 2.4e-7
    assert rt.rows[1].passed is False   # 10/2e6 = 5e-6 > 2.4e-7
    assert rt.rows[0].limit == "± 2,4×10⁻⁷"
    assert rt.passed is False   # 1 dòng fail -> cả bảng fail


def test_map_table_value_vs_parsed_threshold():
    d = _descriptor(rows=[
        RowDef(key="r1", limit="≤ 15 mVrms", raw_count=1),
        RowDef(key="r2", limit="≤ 15 mVrms", raw_count=1),
    ], pass_rule={"type": "value_vs_parsed_threshold"})
    rt = table_engine.map_table(d, _step_results(12.3, 16.0))
    assert rt.rows[0].passed is True
    assert rt.rows[1].passed is False
    assert rt.passed is False


def test_map_table_correction_vs_reference_never_has_pass_fail():
    """Bảng hiệu chuẩn (kiểu QTHC 2.515) — error = chuẩn - đo được, KHÔNG có
    khái niệm Đạt/Không đạt, dù đo lệch bao nhiêu."""
    d = _descriptor(rows=[RowDef(key="r1", reference=1.0, raw_count=1)],
                     pass_rule={"type": "correction_vs_reference"})
    rt = table_engine.map_table(d, _step_results(0.95))
    assert rt.rows[0].error == 1.0 - 0.95
    assert rt.rows[0].passed is None
    assert rt.passed is None


def test_map_table_raw_count_averages_multiple_readings():
    d = _descriptor(rows=[RowDef(key="r1", reference=10.0, raw_count=3)],
                     pass_rule={"type": "none"})
    rt = table_engine.map_table(d, _step_results(9.0, 10.0, 11.0))
    assert rt.rows[0].value_measured == 10.0
    assert rt.rows[0].raw_readings == [9.0, 10.0, 11.0]


def test_map_table_measured_count_excludes_extra_slots_from_formula():
    """Dòng đẩy 2 report_val (giá trị đo rồi đến sai số kịch bản tự tính sẵn,
    vd Bảng A5 QTKĐ 2.461) -> raw_count=2 nhưng measured_count=1 phải khiến
    value_measured/error/passed chỉ tính từ giá trị đo (slot đầu), KHÔNG
    trộn lẫn với slot sai số (chỉ để report_val() hiển thị lại, không phải
    nguồn công thức)."""
    d = _descriptor(rows=[
        RowDef(key="f1", freq_set=1e6, reference=1e6, raw_count=2, measured_count=1,
               value_format_seq=["freq", "sci"]),
    ], pass_rule={"type": "relative_error_vs_fixed_limit",
                  "params": {"fixed_limit": 2.4e-7, "limit_str": "± 2,4×10⁻⁷"}})
    # 2 report_val: 1_000_000.1 (đo được) rồi 1e-7 (sai số kịch bản tự tính).
    rt = table_engine.map_table(d, _step_results(1_000_000.1, 1e-7))
    assert rt.rows[0].value_measured == 1_000_000.1
    assert rt.rows[0].raw_readings == [1_000_000.1, 1e-7]
    assert rt.rows[0].passed is True   # 0.1/1e6 = 1e-7 <= 2.4e-7, tính từ ĐÚNG slot đo được


def test_map_table_leftover_values_produce_note():
    d = _descriptor(rows=[RowDef(key="r1", raw_count=1)], pass_rule={"type": "none"})
    rt = table_engine.map_table(d, _step_results(1.0, 2.0, 3.0))
    assert rt.rows[0].value_measured == 1.0
    assert "A9" in rt.note
    assert "2" in rt.note   # 2 giá trị dư chưa dùng tới
