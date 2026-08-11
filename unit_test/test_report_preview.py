"""
unit_test/test_report_preview.py
=================================
Test cho gui.report_preview.build_wysiwyg_table — khung xem trước/rà soát
kết quả dùng ở Bước 2/Bước 3.

TEMPLATE_FREQ (A1-A8) và TEMPLATE_POWER (A1-A3) có builder riêng khớp
ĐÚNG layout docx thật (đăng ký trong _TEMPLATE_BUILDERS, xem
unit_test/test_report_preview_freq_power.py) — mọi template/table_id KHÁC
(chưa đăng ký) rơi về _build_generic (khung rà soát chung, không khớp
pixel). Các test dưới đây xác nhận đúng hành vi fallback này + các helper
dùng chung (checkbox/status column, khung rỗng) vẫn hoạt động đúng.
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox

from core.session import TableRow
from gui import report_preview
from gui.report_preview import build_wysiwyg_table, _add_checkbox_column, _add_status_column, _new_table

_app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# build_wysiwyg_table — fallback khi không có builder riêng (mọi template hiện nay)
# ---------------------------------------------------------------------------

def test_empty_rows_shows_placeholder():
    tbl = build_wysiwyg_table("BAT_KY", "A5", [])
    assert tbl.columnCount() == 1
    assert "chưa" in tbl.item(0, 0).text().lower()


def test_no_registered_builder_falls_back_to_generic_table():
    """TEMPLATE_FREQ có builder riêng cho A1-A8 (khớp đúng docx) — dùng
    1 table_id KHÔNG tồn tại (A99) để vẫn đi qua nhánh fallback chung."""
    rows = [TableRow(key="x", value_measured=1.0, passed=True)]
    tbl = build_wysiwyg_table("TEMPLATE_FREQ", "A99", rows)
    assert tbl.rowCount() == 1
    assert tbl.item(0, 0).text() == "x"


def test_unknown_template_id_falls_back_to_generic_table():
    rows = [TableRow(key="x", value_measured=1.0, passed=True)]
    tbl = build_wysiwyg_table("KHONG_TON_TAI", "A5", rows)
    assert tbl.rowCount() == 1
    assert tbl.item(0, 0).text() == "x"


def test_empty_rows_still_shows_placeholder_not_crash():
    tbl = build_wysiwyg_table("KHONG_TON_TAI", "A5", [])
    assert tbl.columnCount() == 1
    assert "chưa có dòng nào được xác nhận" in tbl.item(0, 0).text().lower()


# ---------------------------------------------------------------------------
# Helper dùng chung (checkbox/status) — vẫn phải hoạt động đúng cho 1
# builder tuỳ biến đăng ký thủ công, mô phỏng bằng 1 builder tối giản dựng
# tại chỗ trong test (không phụ thuộc template thật nào).
# ---------------------------------------------------------------------------

def _fake_builder(rows, with_checkbox=False, on_toggle=None,
                   with_status=False, on_status_change=None,
                   interactive=True, on_value_edited=None,
                   recompute_row=None, measured_counts=None):
    tbl = _new_table(len(rows), ["Khoá", "Giá trị"])
    for i, r in enumerate(rows):
        tbl.setItem(i, 0, QtWidgets.QTableWidgetItem(r.key))
        tbl.setItem(i, 1, QtWidgets.QTableWidgetItem(str(r.value_measured)))
    row_groups = [(i, i + 1, r) for i, r in enumerate(rows)]
    if with_status:
        _add_status_column(tbl, row_groups, on_status_change, enabled=interactive)
    if with_checkbox:
        _add_checkbox_column(tbl, row_groups, on_toggle, enabled=interactive)
    return tbl


@pytest.fixture(autouse=True)
def _register_fake_builder():
    report_preview._TEMPLATE_BUILDERS["FAKE_TPL"] = {"A1": _fake_builder}
    yield
    report_preview._TEMPLATE_BUILDERS.pop("FAKE_TPL", None)


def test_registered_builder_used_instead_of_placeholder():
    rows = [TableRow(key="5Hz", value_measured=5.0)]
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows)
    assert tbl.columnCount() == 2
    assert tbl.item(0, 0).text() == "5Hz"


def test_with_checkbox_adds_column_and_toggle_writes_confirmed():
    rows = [TableRow(key="5Hz", value_measured=5.0, confirmed=False)]
    toggled = []
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_checkbox=True,
                              on_toggle=lambda: toggled.append(1))
    assert tbl.horizontalHeaderItem(0).text() == "Đưa vào\nbáo cáo"
    assert tbl.columnCount() == 3   # 2 cột dữ liệu + 1 cột checkbox
    chk_widget = tbl.cellWidget(0, 0)
    assert chk_widget is not None
    chk = chk_widget.findChild(QCheckBox)
    chk.setChecked(True)
    assert rows[0].confirmed is True
    assert toggled == [1]


def test_status_column_appended_at_end_with_default_from_passed():
    rows = [TableRow(key="5Hz", value_measured=5.0, passed=True)]
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_status=True)
    assert tbl.columnCount() == 3   # 2 cột dữ liệu + 1 status
    assert tbl.horizontalHeaderItem(2).text() == "Đạt/\nKhông đạt"
    combo = tbl.cellWidget(0, 2)
    assert isinstance(combo, QComboBox)
    assert combo.currentIndex() == 1   # passed=True -> "✅ Đạt"


def test_status_column_defaults_to_dash_when_passed_none():
    rows = [TableRow(key="5Hz", value_measured=5.0, passed=None)]
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_status=True)
    combo = tbl.cellWidget(0, tbl.columnCount() - 1)
    assert combo.currentIndex() == 0   # "—"


def test_status_combobox_writes_back_to_passed_and_calls_callback():
    rows = [TableRow(key="5Hz", value_measured=5.0, passed=None)]
    changed = []
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_status=True,
                              on_status_change=lambda: changed.append(1))
    combo = tbl.cellWidget(0, tbl.columnCount() - 1)
    combo.setCurrentIndex(2)   # "❌ Không đạt"
    assert rows[0].passed is False
    assert changed == [1]
    combo.setCurrentIndex(1)   # "✅ Đạt"
    assert rows[0].passed is True


def test_interactive_false_shows_but_disables_widgets():
    rows = [TableRow(key="5Hz", value_measured=5.0, passed=None, confirmed=False)]
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_checkbox=True, with_status=True,
                              interactive=False)
    assert tbl.columnCount() == 4   # vẫn đủ cột như khi interactive=True
    chk = tbl.cellWidget(0, 0).findChild(QCheckBox)
    combo = tbl.cellWidget(0, 3)
    assert chk.isEnabled() is False
    assert combo.isEnabled() is False


def test_checkbox_and_status_together_correct_order():
    """Khi bật cả 2: [checkbox][...dữ liệu...][status]."""
    rows = [TableRow(key="5Hz", value_measured=5.0, passed=True, confirmed=False)]
    tbl = build_wysiwyg_table("FAKE_TPL", "A1", rows, with_checkbox=True, with_status=True)
    assert tbl.columnCount() == 4   # 2 cột dữ liệu + checkbox (đầu) + status (cuối)
    assert tbl.horizontalHeaderItem(0).text() == "Đưa vào\nbáo cáo"
    assert tbl.horizontalHeaderItem(3).text() == "Đạt/\nKhông đạt"
    assert tbl.cellWidget(0, 0).findChild(QCheckBox) is not None
    assert isinstance(tbl.cellWidget(0, 3), QComboBox)
