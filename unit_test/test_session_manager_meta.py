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
from core.session import CalibrationSession, SessionTest, ReportTable, TableRow
from gui.session_manager import (
    _MetaTab, _table_has_pass_fail, SessionManagerWindow, _StepRail, _ExportTab,
    _TestReviewTab,
)

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


# ---------------------------------------------------------------------------
# BUG-09/10: "✓ hoàn thành" ở rail trước đây chỉ xét VỊ TRÍ điều hướng
# (i < index) — bấm sang Bước 2 khi chưa chọn mẫu/chưa đo gì vẫn hiện ✓ cho
# cả Bước 1 và Bước 2. Bước 3: bài LỖI hiện "⏳" (chờ) thay vì báo lỗi; "Tổng
# điểm đo" thực ra đếm SỐ BÀI, không phải số điểm đo.
# ---------------------------------------------------------------------------

def test_step_rail_set_current_only_marks_explicitly_completed_steps():
    steps = [("Bước 1", "s1"), ("Bước 2", "s2"), ("Bước 3", "s3")]
    rail = _StepRail(steps)
    try:
        # Đi tới Bước 2 (index=1) nhưng KHÔNG báo bước nào đã hoàn thành
        # thật -> Bước 1 (index 0, "đi qua" rồi) KHÔNG được tự thành ✓.
        rail.set_current(1, completed=set())
        assert rail._dots[0].text() == "○", "Bước 1 hiện ✓ dù chưa hoàn thành thật (BUG-09)"
        assert rail._dots[1].text() == "●"
        assert rail._dots[2].text() == "○"

        rail.set_current(1, completed={0})
        assert rail._dots[0].text() == "✓"
        assert rail._dots[1].text() == "●"
    finally:
        rail.deleteLater()


def test_step_rail_set_current_without_completed_arg_keeps_old_behavior():
    """Không truyền completed -> dùng lại y hệt hành vi cũ (i < index) cho
    chỗ gọi nào chưa kịp cập nhật — không phải hành vi MONG MUỐN lâu dài,
    chỉ để không crash nơi khác lỡ còn gọi set_current(index) trần."""
    steps = [("Bước 1", "s1"), ("Bước 2", "s2"), ("Bước 3", "s3")]
    rail = _StepRail(steps)
    try:
        rail.set_current(2)
        assert rail._dots[0].text() == "✓"
        assert rail._dots[1].text() == "✓"
        assert rail._dots[2].text() == "●"
    finally:
        rail.deleteLater()


def _fake_window(template_id: str, tests: list):
    """self giả chỉ cần ._session — _completed_steps() không đụng gì khác."""
    from types import SimpleNamespace
    session = SimpleNamespace(template_id=template_id, tests=tests)
    fake_self = SimpleNamespace(_session=session)
    fake_self._completed_steps = lambda: SessionManagerWindow._completed_steps(fake_self)
    return fake_self


def test_completed_steps_step1_requires_template_selected():
    win = _fake_window("", [])
    assert 0 not in win._completed_steps(), "Bước 1 hiện hoàn thành dù chưa chọn mẫu (BUG-09)"

    win2 = _fake_window("TEMPLATE_FREQ", [])
    assert 0 in win2._completed_steps()


def test_completed_steps_step2_requires_all_enabled_tests_done():
    t_pending = SessionTest(table_id="A1", enabled=True, status="pending")
    win = _fake_window("TEMPLATE_FREQ", [t_pending])
    assert 1 not in win._completed_steps(), (
        "Bước 2 hiện hoàn thành dù 0/8 bài đã đo (BUG-09)")

    t_failed = SessionTest(table_id="A1", enabled=True, status="failed")
    win_failed = _fake_window("TEMPLATE_FREQ", [t_failed])
    assert 1 not in win_failed._completed_steps(), (
        "Bước 2 hiện hoàn thành dù có bài đang Lỗi (BUG-09)")

    t_done = SessionTest(table_id="A1", enabled=True, status="done")
    win_done = _fake_window("TEMPLATE_FREQ", [t_done])
    assert 1 in win_done._completed_steps()

    # Bài bị TẮT (enabled=False) không tính vào yêu cầu "mọi bài bật đã đo".
    t_disabled_pending = SessionTest(table_id="A2", enabled=False, status="pending")
    win_mixed = _fake_window("TEMPLATE_FREQ", [t_done, t_disabled_pending])
    assert 1 in win_mixed._completed_steps()


def test_completed_steps_step2_empty_enabled_list_not_completed():
    """Không có bài nào được bật -> không thể coi là 'đã đo xong hết'."""
    win = _fake_window("TEMPLATE_FREQ", [])
    assert 1 not in win._completed_steps()


def test_export_tab_shows_error_icon_for_failed_test_not_hourglass():
    """BUG-10: bài LỖI (status='failed', result_table rỗng/None) trước đây
    rơi vào cùng nhánh "n == 0" như bài CHƯA CHẠY -> hiện "⏳" (chờ) thay vì
    báo lỗi thật."""
    tab = _ExportTab()
    try:
        t = SessionTest(table_id="A1", name="Bảng A1", enabled=True, status="failed")
        tab.refresh([t], None, "TEMPLATE_FREQ")
        item_text = tab.lst_tests.item(0).text()
        assert item_text.startswith("❌"), f"Vẫn hiện sai icon cho bài Lỗi: {item_text!r}"
    finally:
        tab.deleteLater()


def test_export_tab_total_stat_label_is_test_count_not_measurement_points():
    """Nhãn "Tổng điểm đo" cũ gây hiểu lầm — counts["total"] thực ra là SỐ
    BÀI (len(tests)), không phải tổng số report_val() của mọi bài. Đổi nhãn
    thành "Tổng số bài" cho khớp đúng ý nghĩa, không đổi cách đếm."""
    tab = _ExportTab()
    try:
        t1 = SessionTest(table_id="A1", enabled=True, status="done",
                         result_table=ReportTable(table_id="A1", rows=[TableRow() for _ in range(19)]))
        t2 = SessionTest(table_id="A2", enabled=True, status="done",
                         result_table=ReportTable(table_id="A2", rows=[TableRow() for _ in range(19)]))
        tab.refresh([t1, t2], None, "TEMPLATE_FREQ")
        assert tab._rs_vals["total"].text() == "2"   # 2 BÀI, không phải 38 điểm đo
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# BUG-23b: nút "Chạy tất cả"/"■ Dừng" ở Bước 2 (và tương tự ở Scenario
# Builder) không đổi style khi bị vô hiệu — background tự đặt riêng không
# có quy tắc :disabled nên vẫn sáng y màu dù setEnabled(False), bấm không
# có tác dụng mà trông như đang bật.
# ---------------------------------------------------------------------------

def test_run_stop_buttons_have_disabled_style_rule():
    tab = _TestReviewTab()
    try:
        assert ":disabled" in tab.btn_run.styleSheet(), (
            "btn_run (Chạy tất cả) không có style riêng cho trạng thái vô hiệu (BUG-23b)")
        assert ":disabled" in tab.btn_stop.styleSheet(), (
            "btn_stop (■ Dừng) không có style riêng cho trạng thái vô hiệu (BUG-23b)")
    finally:
        tab.deleteLater()


def test_stop_button_starts_disabled_and_run_button_enabled():
    """Trạng thái khởi tạo đúng — setEnabled(False)/True khớp UI thật."""
    tab = _TestReviewTab()
    try:
        assert tab.btn_stop.isEnabled() is False
        assert tab.btn_run.isEnabled() is True
    finally:
        tab.deleteLater()


def test_progress_bar_stays_visible_across_set_running_no_layout_jump():
    """R4-06 (test_reports/2026-10-08_round5): trước đây progress.setVisible()
    đổi theo running -> đổi chiều cao layout, cụm nút Chạy/Dừng bị đẩy lên
    ~26px ngay lúc bắt đầu chạy. Progress bar phải LUÔN hiện (chỉ đổi nội
    dung/giá trị), không đổi visibility, để chiều cao layout cố định.
    isHidden() phản ánh đúng việc CÓ gọi setVisible(False)/hide() hay không,
    không phụ thuộc cửa sổ cha đã show() thật trên màn hình chưa (khác
    isVisible())."""
    tab = _TestReviewTab()
    try:
        assert tab.progress.isHidden() is False, "Progress bar bị ẩn ngay từ đầu (R4-06)"
        tab.set_running(True)
        assert tab.progress.isHidden() is False
        tab.set_running(False)
        assert tab.progress.isHidden() is False, (
            "set_running() vẫn ẩn/hiện progress bar -> gây nhảy layout (R4-06)")
    finally:
        tab.deleteLater()


# ---------------------------------------------------------------------------
# R4-02 (test_reports/2026-10-08_round4): bài bị bấm "Dừng" giữa chừng vẫn bị
# đánh "✅ Xong"/"Đã đo" dù dữ liệu CHƯA chạy hết — SessionManagerWindow.
# _on_test_done() trước đây chỉ phân biệt "tự dừng vì lỗi thiết bị"
# (stop_reason) với "chạy xong", không có nhánh riêng cho người dùng CHỦ
# ĐỘNG bấm "Dừng" (_TestWorker._stop, không đi qua ScenarioRunner.stop_reason).
# ---------------------------------------------------------------------------

def _fake_on_test_done_self(test: SessionTest):
    """self giả cho SessionManagerWindow._on_test_done() — chỉ cần các
    thuộc tính/method mà hàm này thật sự đụng tới. _CLEANUP_NOT_RUN_HINT là
    thuộc tính CẤP CLASS (R5-01) — SimpleNamespace không tự kế thừa được,
    phải gán tay."""
    from types import SimpleNamespace
    session = SimpleNamespace(template_id="__KHONG_TON_TAI__", tests=[test])
    return SimpleNamespace(
        _session=session,
        _step_results_current=[],
        _step_review=SimpleNamespace(refresh_row=lambda i: None, set_running=lambda b: None),
        _log=lambda *a, **k: None,
        _log_ram=lambda *a, **k: None,
        _after_single_or_continue=lambda: None,
        _CLEANUP_NOT_RUN_HINT=SessionManagerWindow._CLEANUP_NOT_RUN_HINT,
    )


def test_on_test_done_user_stopped_marks_status_stopped_not_done(monkeypatch):
    from gui import session_manager as sm_mod

    warned = []
    monkeypatch.setattr(sm_mod.QMessageBox, "warning",
                         lambda *a, **k: warned.append(a[1] if len(a) > 1 else ""))

    test = SessionTest(table_id="A1", name="Bảng A1", enabled=True, status="running")
    fake_self = _fake_on_test_done_self(test)

    SessionManagerWindow._on_test_done(fake_self, 0, 4, "", True)

    assert test.status == "stopped", (
        f"Bài dừng giữa chừng bị đánh status={test.status!r} — vẫn tính như "
        f"đã đo xong (R4-02)")
    assert warned, "Không cảnh báo trên giao diện khi dừng sớm (R5-01)"


def test_on_test_done_normal_finish_still_marks_done():
    """Không được vô tình đổi hành vi chạy XONG bình thường (stopped_early=False)."""
    test = SessionTest(table_id="A1", name="Bảng A1", enabled=True, status="running")
    fake_self = _fake_on_test_done_self(test)

    SessionManagerWindow._on_test_done(fake_self, 0, 19, "", False)

    assert test.status == "done"


def test_on_test_done_device_failure_warns_cleanup_not_run_too(monkeypatch):
    """R5-01: dừng do SỰ CỐ THIẾT BỊ cũng là dừng SỚM — thông báo lỗi phải
    kèm cùng lời nhắc dọn dẹp chưa chạy như khi người dùng tự bấm Dừng,
    không chỉ riêng trường hợp bấm Dừng tay."""
    from gui import session_manager as sm_mod

    shown = []
    monkeypatch.setattr(sm_mod.QMessageBox, "critical",
                         lambda *a, **k: shown.append(a[2] if len(a) > 2 else ""))

    test = SessionTest(table_id="A1", name="Bảng A1", enabled=True, status="running")
    fake_self = _fake_on_test_done_self(test)

    SessionManagerWindow._on_test_done(fake_self, 0, 3, "Mất kết nối GPIB", False)

    assert test.status == "failed"
    assert shown and "CHƯA chạy" in shown[0], (
        f"Thông báo lỗi thiết bị không nhắc dọn dẹp chưa chạy (R5-01): {shown}")


def test_export_tab_shows_stopped_icon_for_stopped_test():
    """Bài status='stopped' phải hiện icon riêng (⛔), tính là "chưa đủ" dù
    có vài dòng lỡ được xác nhận — không lẫn với bài đã đo xong, chỉ đang
    chờ xác nhận (R4-02)."""
    tab = _ExportTab()
    try:
        t = SessionTest(table_id="A1", name="Bảng A1", enabled=True, status="stopped")
        tab.refresh([t], None, "TEMPLATE_FREQ")
        item_text = tab.lst_tests.item(0).text()
        assert item_text.startswith("⛔"), f"Vẫn hiện sai icon cho bài Dừng dở: {item_text!r}"
    finally:
        tab.deleteLater()


def test_completed_steps_step2_not_completed_when_test_stopped():
    t_stopped = SessionTest(table_id="A1", enabled=True, status="stopped")
    win = _fake_window("TEMPLATE_FREQ", [t_stopped])
    assert 1 not in win._completed_steps(), (
        "Bước 2 hiện hoàn thành dù có bài bị Dừng giữa chừng (R4-02)")


def test_confirm_stopped_tests_warning_blocks_export_when_user_says_no(monkeypatch):
    """Trước đây xuất thẳng báo cáo thiếu dữ liệu mà không cảnh báo gì (R4-02)
    — giờ phải hỏi lại, và tôn trọng lựa chọn "Không" của người dùng (không
    xuất)."""
    from types import SimpleNamespace
    from gui import session_manager as sm_mod

    t_stopped = SessionTest(table_id="A1", enabled=True, status="stopped")
    t_done = SessionTest(table_id="A2", enabled=True, status="done")
    fake_self = SimpleNamespace(_session=SimpleNamespace(tests=[t_stopped, t_done]))

    asked = {}
    monkeypatch.setattr(sm_mod, "confirm_yes_no",
                         lambda *a, **k: (asked.update(title=a[1]), False)[1])

    result = SessionManagerWindow._confirm_stopped_tests_warning(fake_self)
    assert result is False
    assert "DỪNG GIỮA CHỪNG" in asked.get("title", "")


def test_confirm_stopped_tests_warning_passes_when_no_stopped_tests():
    from types import SimpleNamespace

    t_done = SessionTest(table_id="A1", enabled=True, status="done")
    fake_self = SimpleNamespace(_session=SimpleNamespace(tests=[t_done]))
    assert SessionManagerWindow._confirm_stopped_tests_warning(fake_self) is True
