"""
unit_test/test_session_manager_meta.py
=========================================
Test các sửa lỗi phát hiện ở vòng test 2026-09-30/10-01
(test_reports/2026-09-30_full_gui/BAO_CAO_TEST.md):

  BUG-04/05: _MetaTab.validate_meta() — ô Nhiệt độ/Độ ẩm/Năm SX gõ sai không
             phải số, Hiệu lực đến sớm hơn Ngày kiểm định, trước đây không
             kiểm tra gì cả, in nguyên văn vào Biên bản/GCN.
  BUG-12:    _table_has_pass_fail() — bảng pass_rule.type == "none" (mẫu
             "hiệu chuẩn") không còn cho chọn Đạt/Không đạt.
"""

import json
from pathlib import Path

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QApplication

from core.table_descriptor import TableDescriptor, RowDef
from core import table_wizard_io as wio
from gui.session_manager import _MetaTab, _table_has_pass_fail

_app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# _MetaTab.validate_meta()
# ---------------------------------------------------------------------------

def test_validate_meta_no_problems_on_defaults():
    tab = _MetaTab()
    try:
        assert tab.validate_meta() == []
    finally:
        tab.deleteLater()


def test_validate_meta_flags_non_numeric_temperature_and_humidity():
    tab = _MetaTab()
    try:
        tab.e_temp.setText("hai mươi")
        tab.e_humidity.setText("150")
        problems = tab.validate_meta()
        assert any("Nhiệt độ" in p for p in problems)
        assert any("Độ ẩm" in p and "150" in p for p in problems)
    finally:
        tab.deleteLater()


def test_validate_meta_accepts_numeric_text_with_unit():
    """Nhiệt độ/Độ ẩm vẫn là ô CHỮ TỰ DO (có thể kèm đơn vị, vd "23 °C") theo
    đúng thiết kế hiện tại (core/session.py: temperature/humidity: str) —
    validate_meta() chỉ cảnh báo khi KHÔNG đọc được số ở đầu chuỗi, không ép
    kiểu số thuần."""
    tab = _MetaTab()
    try:
        tab.e_temp.setText("23 °C")
        tab.e_humidity.setText("55 %RH")
        assert tab.validate_meta() == []
    finally:
        tab.deleteLater()


def test_validate_meta_flags_invalid_year():
    tab = _MetaTab()
    try:
        tab.e_year.setText("abc")
        assert any("Năm sản xuất" in p for p in tab.validate_meta())
    finally:
        tab.deleteLater()


def test_validate_meta_flags_valid_until_before_inspection_date():
    tab = _MetaTab()
    try:
        tab.de_date.setDate(QDate(2028, 9, 30))
        tab.de_valid.setDate(QDate(2020, 1, 30))
        problems = tab.validate_meta()
        assert any("Hiệu lực đến" in p and "sớm hơn" in p for p in problems)
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# _table_has_pass_fail()
# ---------------------------------------------------------------------------

def _build_fixture_template(base_dir: Path, template_id: str, pass_rule: dict):
    tpl_dir = base_dir / template_id
    (tpl_dir / "tables").mkdir(parents=True)
    meta = {"template_id": template_id, "template_name": template_id,
            "kind": "hieu_chuan", "dut_models": ["X1"], "standard": "TEST"}
    (tpl_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    descriptor = TableDescriptor(
        schema_version=1, table_id="T1", name="Bảng thử", order=1, scenario_file="",
        layout="repeated_rows", value_unit="Hz",
        rows=[RowDef(key="f1", raw_count=1)], columns=[], pass_rule=pass_rule, merge=[],
    )
    wio.write_descriptor_json(descriptor, tpl_dir / "tables")


def test_table_has_pass_fail_false_for_pass_rule_none(tmp_path, monkeypatch):
    import core.report_templates.generic as generic_mod
    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    _build_fixture_template(tmp_path, "TPL_NONE", {"type": "none"})

    assert _table_has_pass_fail("TPL_NONE", "T1") is False


def test_table_has_pass_fail_true_for_real_pass_rule(tmp_path, monkeypatch):
    import core.report_templates.generic as generic_mod
    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    _build_fixture_template(tmp_path, "TPL_REAL", {"type": "value_vs_parsed_threshold"})

    assert _table_has_pass_fail("TPL_REAL", "T1") is True


def test_table_has_pass_fail_true_when_template_unknown():
    """Không xác định được (template/bảng không tồn tại) -> True (an toàn,
    không ẩn mất cột ở bảng thật sự cần nó do lỗi cấu hình khác)."""
    assert _table_has_pass_fail("KHONG_TON_TAI", "T1") is True
