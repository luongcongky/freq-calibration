"""
unit_test/test_table_wizard_io.py
====================================
Test phần "không Qt" của "Thêm bảng báo cáo mới" (core/table_wizard_io.py)
— dựng TableDescriptor từ dữ liệu người dùng nhập ở màn hình review, ghi
JSON, đọc file .docx đã gắn tag tay để gợi ý điền form/cảnh báo mã bảng
thiếu. KHÔNG còn quét/đoán cấu trúc bảng hay tự động chèn tag (quản trị
viên tự gõ tag Jinja trực tiếp trong Word).
"""

from pathlib import Path

import pytest
from docx import Document

from core import table_wizard_io as wio
from core.table_descriptor import load_table_descriptor


@pytest.mark.parametrize("text,expected", [
    ("100000", 100000.0), ("1,5", 1.5), (" 42 ", 42.0),
    ("100 kHz", None), ("≤ 15 mVrms", None), ("", None), (None, None),
])
def test_guess_bare_number(text, expected):
    assert wio.guess_bare_number(text) == expected


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def test_validate_table_id_available(tmp_path):
    assert wio.validate_table_id_available(tmp_path, "") is not None
    assert wio.validate_table_id_available(tmp_path, "A 9") is not None
    assert wio.validate_table_id_available(tmp_path, "A9") is None
    (tmp_path / "A9.json").write_text("{}", encoding="utf-8")
    assert wio.validate_table_id_available(tmp_path, "A9") is not None


def test_validate_rows():
    pass_rule = {"type": "relative_error_vs_fixed_limit", "params": {"fixed_limit": 1e-7, "limit_str": "x"}}
    rows_missing_ref = [wio.WizardRowSpec(key="a", reference=None)]
    assert wio.validate_rows(rows_missing_ref, pass_rule) is not None
    rows_ok = [wio.WizardRowSpec(key="a", reference=1e6)]
    assert wio.validate_rows(rows_ok, pass_rule) is None
    rows_dup_key = [wio.WizardRowSpec(key="a", reference=1e6), wio.WizardRowSpec(key="a", reference=2e6)]
    assert wio.validate_rows(rows_dup_key, pass_rule) is not None


def test_pass_rule_allowed_for_unit():
    assert wio.pass_rule_allowed_for_unit("value_vs_parsed_threshold", "mVrms") is True
    assert wio.pass_rule_allowed_for_unit("value_vs_parsed_threshold", "dBm") is True
    assert wio.pass_rule_allowed_for_unit("value_vs_parsed_threshold", "W") is False
    assert wio.pass_rule_allowed_for_unit("relative_error_vs_fixed_limit", "W") is True


# ---------------------------------------------------------------------------
# build_descriptor — không còn cột vật lý/merge, raw_count luôn = 1
# ---------------------------------------------------------------------------

def _spec(**overrides) -> wio.WizardTableSpec:
    kwargs = dict(
        table_id="A9", name="Bảng thử nghiệm", order=9, value_unit="dBm",
        value_format="dbm",
        rows=[wio.WizardRowSpec(key="f1", freq_set=1e6, limit="≤ 15 mVrms"),
              wio.WizardRowSpec(key="f2", freq_set=2e6, limit="≤ 15 mVrms")],
        pass_rule={"type": "value_vs_parsed_threshold"}, gcn=None,
    )
    kwargs.update(overrides)
    return wio.WizardTableSpec(**kwargs)


def test_build_descriptor_raw_count_always_one():
    d = wio.build_descriptor(_spec())
    assert d.columns == []
    assert d.merge == []
    assert all(r.raw_count == 1 for r in d.rows)


def test_build_descriptor_json_roundtrip(tmp_path):
    spec = _spec()
    d = wio.build_descriptor(spec)
    out = wio.write_descriptor_json(d, tmp_path)
    reloaded = load_table_descriptor(out)
    assert reloaded.table_id == "A9"
    assert reloaded.value_format == "dbm"
    assert reloaded.to_dict() == d.to_dict()


def test_build_descriptor_keeps_gcn_field():
    spec = _spec(gcn={"param_name": "Độ nhạy", "limit_str": "≤ 15 mVrms"})
    d = wio.build_descriptor(spec)
    assert d.gcn == {"param_name": "Độ nhạy", "limit_str": "≤ 15 mVrms"}


# ---------------------------------------------------------------------------
# is_advanced_table / descriptor_to_spec — phân biệt bảng "đơn giản" (form
# Quản lý mẫu báo cáo sửa được) với bảng "nâng cao" (nhiều report_val()/
# dòng — measured_count/value_format_seq/uncertainty_index — chỉ xem JSON).
# ---------------------------------------------------------------------------

def test_is_advanced_table_false_for_plain_descriptor():
    d = wio.build_descriptor(_spec())
    assert wio.is_advanced_table(d) is False


@pytest.mark.parametrize("field_name,value", [
    ("measured_count", 5), ("value_format_seq", ["dbm", "sci"]), ("uncertainty_index", 6),
])
def test_is_advanced_table_true_when_any_advanced_field_set(field_name, value):
    d = wio.build_descriptor(_spec())
    setattr(d.rows[0], field_name, value)
    assert wio.is_advanced_table(d) is True


def test_descriptor_to_spec_round_trips_simple_table():
    original_spec = _spec()
    d = wio.build_descriptor(original_spec)
    spec = wio.descriptor_to_spec(d)
    assert spec.table_id == "A9"
    assert spec.name == "Bảng thử nghiệm"
    assert spec.value_unit == "dBm"
    assert spec.value_format == "dbm"
    assert spec.pass_rule == {"type": "value_vs_parsed_threshold"}
    assert [r.key for r in spec.rows] == ["f1", "f2"]
    assert spec.rows[0].limit == "≤ 15 mVrms"
    # build_descriptor(descriptor_to_spec(d)) phải cho lại ĐÚNG descriptor cũ
    assert wio.build_descriptor(spec).to_dict() == d.to_dict()


# ---------------------------------------------------------------------------
# scan_meta_paragraphs — gợi ý điền sẵn form meta khi tạo mẫu mới
# ---------------------------------------------------------------------------

def test_scan_meta_paragraphs(tmp_path):
    doc = Document()
    doc.add_paragraph("Ký hiệu: CNT-90XL")
    doc.add_paragraph("Không có dấu hai chấm ở đây")
    doc.add_paragraph("Số hiệu: SN12345")
    path = tmp_path / "meta.docx"
    doc.save(str(path))

    pairs = wio.scan_meta_paragraphs(path)
    labels = {p.label: p.value for p in pairs}
    assert labels.get("Ký hiệu") == "CNT-90XL"
    assert labels.get("Số hiệu") == "SN12345"
    assert "Không có dấu hai chấm ở đây" not in labels


# ---------------------------------------------------------------------------
# find_missing_table_ids — cảnh báo nhẹ, chỉ đọc, không sửa file
# ---------------------------------------------------------------------------

def _docx_with_tags(tmp_path, name, tags: list) -> Path:
    doc = Document()
    for t in tags:
        doc.add_paragraph(t)
    path = tmp_path / name
    doc.save(str(path))
    return path


def test_find_missing_table_ids_detects_typo(tmp_path):
    path = _docx_with_tags(tmp_path, "bienban.docx",
                            ["{% if tables.A2.enabled %}", "{{ tables.A2.report_val() }}", "{% endif %}"])
    assert wio.find_missing_table_ids(path, ["A2", "A9"]) == ["A9"]


def test_find_missing_table_ids_all_present(tmp_path):
    path = _docx_with_tags(tmp_path, "bienban.docx",
                            ["{{ tables.A2.report_val() }}", "{{ tables.A9.result }}"])
    assert wio.find_missing_table_ids(path, ["A2", "A9"]) == []


def test_find_missing_table_ids_reads_table_cells_too(tmp_path):
    doc = Document()
    tbl = doc.add_table(rows=1, cols=1)
    tbl.cell(0, 0).text = "{{ tables.A2.report_val() }}"
    path = tmp_path / "bienban.docx"
    doc.save(str(path))
    assert wio.find_missing_table_ids(path, ["A2"]) == []
