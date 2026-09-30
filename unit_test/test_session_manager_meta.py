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
from gui.session_manager import _MetaTab, _table_has_pass_fail, SessionManagerWindow

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


def test_table_has_pass_fail_false_for_correction_vs_reference(tmp_path, monkeypatch):
    """Đúng case khách báo lại ở vòng test lai (BUG-12 vẫn chưa sửa đúng):
    TEMPLATE_POWER A1 dùng pass_rule.type = "correction_vs_reference" (bảng
    hiệu chuẩn, apply_pass_rule() luôn gán passed=None — xem
    core/table_engine.py), KHÔNG phải "none" — lần sửa trước chỉ chặn
    "none" nên cột Đạt/Không đạt vẫn lọt qua cho loại này."""
    import core.report_templates.generic as generic_mod
    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    _build_fixture_template(tmp_path, "TPL_CORRECTION", {"type": "correction_vs_reference"})

    assert _table_has_pass_fail("TPL_CORRECTION", "T1") is False


def test_table_has_pass_fail_true_when_template_unknown():
    """Không xác định được (template/bảng không tồn tại) -> True (an toàn,
    không ẩn mất cột ở bảng thật sự cần nó do lỗi cấu hình khác)."""
    assert _table_has_pass_fail("KHONG_TON_TAI", "T1") is True


# ---------------------------------------------------------------------------
# REG-01: đổi mẫu báo cáo xoá sạch thông tin phiên (Kiểm định viên, Số GCN,
# Nhiệt độ, Serial, cả 2 ngày) — hồi quy từ bản sửa BUG-07. Nguyên nhân:
# _apply_template_defaults()/_offer_reload_active_template() gọi
# _MetaTab.load_from(session) để hiện lại dut.name/manufacturer MỚI, nhưng
# session.meta vẫn là snapshot CŨ (chưa đồng bộ các ô người dùng vừa gõ) ->
# load_from() ghi đè widget bằng dữ liệu rỗng/cũ đó. Fix: đồng bộ
# save_meta_fields_to(session) TRƯỚC khi fill_session_defaults()/load_from().
# ---------------------------------------------------------------------------

def test_template_switch_sequence_preserves_unsynced_fields(tmp_path, monkeypatch):
    from datetime import date as _date
    from core.report_templates import get_template
    from core.session import CalibrationSession
    import core.report_templates.generic as generic_mod

    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    _build_fixture_template(tmp_path, "TPL_NEW", {"type": "none"})
    meta_path = tmp_path / "TPL_NEW" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["dut_manufacturer_default"] = "R&S"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    tab = _MetaTab()
    try:
        # Người dùng gõ tay 1 loạt ô ở Bước 1 — CHƯA qua _sync_meta() lần nào.
        tab.e_name.setText("Máy đếm tần số")
        tab.e_mfr.setText("Pendulum")
        tab.e_serial.setText("SN-123")
        tab.e_operator.setText("Nguyễn Văn A")
        tab.e_cert.setText("GCN-001")
        tab.e_temp.setText("23 °C")
        tab.de_date.setDate(QDate(2028, 9, 30))
        tab.de_valid.setDate(QDate(2029, 9, 30))

        session = CalibrationSession()
        tpl = get_template("TPL_NEW")

        # Đúng chuỗi gọi của _on_template_changed() sau fix REG-01.
        tab.save_meta_fields_to(session)
        tpl.fill_session_defaults(session)
        tab.load_from(session)

        assert tab.e_operator.text() == "Nguyễn Văn A", "Kiểm định viên bị xoá (REG-01)"
        assert tab.e_cert.text() == "GCN-001", "Số GCN bị xoá (REG-01)"
        assert tab.e_temp.text() == "23 °C", "Nhiệt độ bị xoá (REG-01)"
        assert tab.e_serial.text() == "SN-123", "Serial bị xoá (REG-01)"
        assert tab.de_date.date() == QDate(2028, 9, 30), "Ngày kiểm định bị reset (REG-01)"
        assert tab.de_valid.date() == QDate(2029, 9, 30), "Hiệu lực đến bị reset (REG-01)"

        # dut.name/manufacturer của mẫu CŨ vẫn được reset/điền đúng theo mẫu MỚI.
        assert tab.e_name.text() == "", "Tên phương tiện của mẫu cũ phải được reset"
        assert tab.e_mfr.text() == "R&S", "Hãng SX phải đổi theo mẫu mới"
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# REG-04: mẫu không có file GCN vẫn mở hộp lưu rồi mới báo lỗi kỹ thuật
# tiếng Anh "Package not found at '...\gcnkd.docx'" — _check_template_file_exists()
# chặn TRƯỚC khi mở hộp lưu, báo tiếng Việt rõ nguyên nhân.
# ---------------------------------------------------------------------------

class _FakeTpl:
    TEMPLATE_NAME = "Mẫu thử"

    def __init__(self, gcnkd_path):
        self.gcnkd_docx_path = gcnkd_path


def test_check_template_file_exists_true_when_file_present(tmp_path):
    gcnkd = tmp_path / "gcnkd.docx"
    gcnkd.write_text("x")
    tpl = _FakeTpl(gcnkd)
    # Gọi hàm không bound (không cần dựng cả SessionManagerWindow nặng) —
    # self chỉ dùng làm parent cho QMessageBox, không truy cập field nào khác.
    assert SessionManagerWindow._check_template_file_exists(None, tpl, "gcnkd_docx_path", "GCN") is True


def test_check_template_file_exists_false_and_warns_when_missing(tmp_path, monkeypatch):
    from gui import session_manager as sm_mod

    warned = []
    monkeypatch.setattr(sm_mod.QMessageBox, "warning",
                         lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""))
    tpl = _FakeTpl(tmp_path / "khong_ton_tai_gcnkd.docx")
    result = SessionManagerWindow._check_template_file_exists(None, tpl, "gcnkd_docx_path", "GCN")
    assert result is False
    assert warned and "chưa có file GCN" in warned[0]


# ---------------------------------------------------------------------------
# REG-07: sau "Mới", rail footer ("Biểu mẫu đang dùng") vẫn hiện tên mẫu CŨ
# dù combobox đã về "— Chọn mẫu —".
# ---------------------------------------------------------------------------

def test_step_rail_set_template_info_clears_to_placeholder():
    from gui.session_manager import _StepRail

    steps = [("Bước 1", "sub1"), ("Bước 2", "sub2"), ("Bước 3", "sub3")]
    rail = _StepRail(steps)
    try:
        rail.set_template_info("QTHC 2.515 : 2021", "Khách – 51079A 0dBm (Excel 5 sheet)")
        assert rail._lbl_tpl_standard.text() == "QTHC 2.515 : 2021"
        assert rail._lbl_tpl_name.text() == "Khách – 51079A 0dBm (Excel 5 sheet)"

        rail.set_template_info("", "")
        assert rail._lbl_tpl_standard.text() == "— Chưa chọn mẫu —"
        assert rail._lbl_tpl_name.text() == ""
    finally:
        rail.deleteLater()
