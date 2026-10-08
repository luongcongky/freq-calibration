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
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from gui.template_manager_dialog import (
    ImportTableFromExcelDialog, TemplateManagerDialog, _is_xlsx_template,
    _find_existing_descriptor, CopyTemplateDialog,
)

_app = QApplication.instance() or QApplication([])


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


# ---------------------------------------------------------------------------
# NEW-03: sau khi "Đọc bảng"/Sao chép/Xoá bảng xong, lựa chọn bên trái nhảy
# sang mẫu ĐẦU danh sách thay vì giữ đúng mẫu đang sửa.
# ---------------------------------------------------------------------------

def _build_minimal_template(base_dir, template_id: str):
    import json
    tpl_dir = base_dir / template_id
    (tpl_dir / "tables").mkdir(parents=True)
    meta = {"template_id": template_id, "template_name": template_id, "kind": "kiem_dinh",
            "dut_models": ["X"], "standard": "T"}
    (tpl_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_reload_list_keeps_selection_on_non_first_template(tmp_path, monkeypatch):
    """tpl_list.clear() tự fire currentItemChanged(None, ...) ngay lúc đó
    (đồng bộ) -> _on_select_template(None) -> _load_template(None) -> xoá
    mất self.template_id TRƯỚC KHI _reload_list() đọc lại nó để chọn đúng
    dòng -> luôn tụt về mẫu ĐẦU danh sách (báo cáo lỗi NEW-03). _reload_list()
    phải đọc self.template_id làm target TRƯỚC khi gọi clear()."""
    import core.report_templates.generic as generic_mod
    import gui.template_manager_dialog as tmd_mod
    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    # gui/template_manager_dialog.py làm "from core.report_templates.generic
    # import TEMPLATES_DIR" — import kiểu này BIND 1 tham chiếu RIÊNG vào
    # namespace của chính module này tại thời điểm import, patch
    # generic_mod.TEMPLATES_DIR ở trên KHÔNG ảnh hưởng gì tới tham chiếu đã
    # bind sẵn này — phải patch thêm bản sao này, nếu không
    # TemplateManagerDialog.tpl_dir vẫn trỏ về thư mục templates/ THẬT của
    # dự án (gây FileNotFoundError khi đọc meta.json của mẫu giả lập).
    monkeypatch.setattr(tmd_mod, "TEMPLATES_DIR", tmp_path)
    _build_minimal_template(tmp_path, "AAA_FIRST")
    _build_minimal_template(tmp_path, "ZZZ_SECOND")

    dlg = TemplateManagerDialog(parent=None)
    try:
        idx = next(i for i in range(dlg.tpl_list.count())
                  if dlg.tpl_list.item(i).data(Qt.UserRole) == "ZZZ_SECOND")
        dlg.tpl_list.setCurrentRow(idx)
        assert dlg.template_id == "ZZZ_SECOND"

        # Đúng chuỗi gọi của _import_table()/_copy_table()/_delete_table()
        # sau khi thao tác thành công.
        dlg._load_template(dlg.template_id)
        dlg._reload_list()

        assert dlg.template_id == "ZZZ_SECOND", (
            f"Nhảy sang mẫu khác sau _reload_list() (NEW-03): {dlg.template_id!r}")
        assert dlg.tpl_list.currentItem().data(Qt.UserRole) == "ZZZ_SECOND"
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# NEW-04: wizard "Thay thế" 1 bảng đã có hỏi xác nhận 2 lần, không tự điền
# sẵn Tên bài test cũ, đặt sai Thứ tự (A1 đang order=1 bị đẩy xuống 3).
# ---------------------------------------------------------------------------

def test_find_existing_descriptor_matches_by_table_id():
    from types import SimpleNamespace
    descriptors = [SimpleNamespace(table_id="A1", name="Bảng A1", order=1),
                   SimpleNamespace(table_id="A2", name="Bảng A2", order=2)]
    found = _find_existing_descriptor(descriptors, "A1")
    assert found is not None and found.name == "Bảng A1" and found.order == 1


def test_find_existing_descriptor_returns_none_when_not_found():
    from types import SimpleNamespace
    descriptors = [SimpleNamespace(table_id="A1", name="Bảng A1", order=1)]
    assert _find_existing_descriptor(descriptors, "A9") is None


# ---------------------------------------------------------------------------
# BUG-23: sao chép CÙNG 1 mẫu 2 lần -> cả 2 bản sao gợi ý ĐÚNG 1 tên hiển thị
# "{gốc} (bản sao)" -> combo Bước 1 không phân biệt được 2 mẫu khác id.
# ---------------------------------------------------------------------------

def test_copy_template_warns_on_duplicate_display_name(tmp_path, monkeypatch):
    import core.report_templates.generic as generic_mod
    import gui.template_manager_dialog as tmd_mod
    monkeypatch.setattr(generic_mod, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(tmd_mod, "TEMPLATES_DIR", tmp_path)
    _build_minimal_template(tmp_path, "TEMPLATE_POWER_V2")
    # Mẫu này đã dùng ĐÚNG tên hiển thị mà bản sao mới sắp tạo ra sẽ trùng.
    meta_path = tmp_path / "TEMPLATE_POWER_V2" / "meta.json"
    import json
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["template_name"] = "TEMPLATE_POWER (bản sao)"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    asked = {}

    def fake_confirm(parent, title, text, default_yes=True):
        asked["title"] = title
        return False   # người dùng chọn Không -> huỷ, KHÔNG được tạo bản sao trùng tên

    monkeypatch.setattr(tmd_mod, "confirm_yes_no", fake_confirm)

    dlg = CopyTemplateDialog("TEMPLATE_POWER", "TEMPLATE_POWER", parent=None)
    try:
        dlg.e_new_id.setText("TEMPLATE_POWER_V3")
        assert dlg.e_new_name.text() == "TEMPLATE_POWER (bản sao)"  # gợi ý mặc định, TRÙNG mẫu đã có ở trên
        dlg._do_copy()

        assert "title" in asked, "Không hỏi xác nhận dù tên hiển thị đã trùng mẫu khác (BUG-23)"
        assert dlg.new_template_id is None, "Vẫn tạo bản sao trùng tên dù người dùng chọn Không"
        assert not (tmp_path / "TEMPLATE_POWER_V3").exists()
    finally:
        dlg.deleteLater()
