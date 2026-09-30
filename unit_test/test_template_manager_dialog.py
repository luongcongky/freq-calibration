"""
unit_test/test_template_manager_dialog.py
=============================================
Test gui/template_manager_dialog.py::ImportTableFromExcelDialog._suggest_table_id()
— REG-06 (test_reports/2026-10-01_regression/BAO_CAO_TEST_LAI.md): wizard
"Đọc bảng từ Excel" gợi ý Mã bảng KHÔNG liên quan tới tag đã có sẵn trong
sheet (sheet có report_val('A1') nhưng gợi ý "A2").

Gọi hàm KHÔNG bound (self giả, chỉ cần existing_descriptors) để không phải
dựng cả dialog (đọc file Excel thật, build UI cho mọi sheet) — chỉ hàm
_suggest_table_id() này là nơi sửa, không đụng gì khác trong class.
"""

from types import SimpleNamespace

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from gui.template_manager_dialog import ImportTableFromExcelDialog, _is_xlsx_template


def _fake_self(existing_table_ids):
    return SimpleNamespace(existing_descriptors=[SimpleNamespace(table_id=t) for t in existing_table_ids])


def _sheet(detected_table_id: str = ""):
    return SimpleNamespace(detected_table_id=detected_table_id)


def test_suggest_table_id_uses_tag_already_in_sheet():
    fake_self = _fake_self(["A2"])
    suggestion = ImportTableFromExcelDialog._suggest_table_id(fake_self, _sheet("A1"))
    assert suggestion == "A1"


def test_suggest_table_id_falls_back_to_next_free_slot_without_tag():
    fake_self = _fake_self(["A1"])
    suggestion = ImportTableFromExcelDialog._suggest_table_id(fake_self, _sheet(""))
    assert suggestion == "A2"


def test_suggest_table_id_prefers_detected_tag_even_if_already_used():
    """Sheet gắn sẵn report_val('A1') và bảng 'A1' ĐÃ TỒN TẠI -> vẫn gợi ý
    "A1" (đúng ý khách: re-import để cập nhật cấu trúc bảng đã có, không
    phải đẩy sang "A2" không liên quan) — _continue() sẽ hỏi xác nhận
    "Thay thế" riêng, không phải việc của _suggest_table_id()."""
    fake_self = _fake_self(["A1"])
    suggestion = ImportTableFromExcelDialog._suggest_table_id(fake_self, _sheet("A1"))
    assert suggestion == "A1"


def test_suggest_table_id_without_sheet_arg_uses_old_next_free_slot_behavior():
    fake_self = _fake_self(["A1", "A2"])
    assert ImportTableFromExcelDialog._suggest_table_id(fake_self, None) == "A3"


# ---------------------------------------------------------------------------
# REG-09: tab "File Word"/hướng dẫn "...file .docx" hiện cả cho mẫu Excel.
# ---------------------------------------------------------------------------

def test_is_xlsx_template_true_when_bienban_xlsx_exists(tmp_path):
    (tmp_path / "bienban.xlsx").write_text("x")
    assert _is_xlsx_template(tmp_path) is True


def test_is_xlsx_template_true_when_only_gcnkd_xlsx_exists(tmp_path):
    (tmp_path / "gcnkd.xlsx").write_text("x")
    assert _is_xlsx_template(tmp_path) is True


def test_is_xlsx_template_false_for_docx_template(tmp_path):
    (tmp_path / "bienban.docx").write_text("x")
    assert _is_xlsx_template(tmp_path) is False


def test_is_xlsx_template_false_when_no_file_at_all(tmp_path):
    assert _is_xlsx_template(tmp_path) is False
