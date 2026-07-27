"""
unit_test/test_report_preview.py
=================================
Test cho:
  - core.result_mapper.TABLE_ROW_KEYS / TABLE_FIELD_KEYS (metadata cho dropdown
    gắn report_tag trong Scenario Builder).
  - gui.report_preview.build_wysiwyg_table (bảng preview khớp layout docx thật,
    tách đúng theo template — CNT-90XL vs NRP2 dùng chung mã "A1".."A3" nhưng
    layout khác nhau, đây chính là bug đã phát hiện và sửa).
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication

from core.result_mapper import TABLE_MAPPERS, TABLE_ROW_KEYS, TABLE_FIELD_KEYS
from core.session import TableRow
from gui.report_preview import build_wysiwyg_table

_app = QApplication.instance() or QApplication([])

CNT90 = "QTKD_2461_CNT90XL"
NRP2 = "QTHC_2515_NRP2"


# ---------------------------------------------------------------------------
# TABLE_ROW_KEYS / TABLE_FIELD_KEYS
# ---------------------------------------------------------------------------

def test_every_table_id_has_row_keys_and_fields():
    for table_id in TABLE_MAPPERS:
        assert table_id in TABLE_ROW_KEYS
        assert TABLE_ROW_KEYS[table_id], f"{table_id} thiếu row_key"
        assert table_id in TABLE_FIELD_KEYS
        assert TABLE_FIELD_KEYS[table_id], f"{table_id} thiếu field"


def test_no_stray_table_ids():
    assert set(TABLE_ROW_KEYS.keys()) == set(TABLE_MAPPERS.keys())
    assert set(TABLE_FIELD_KEYS.keys()) == set(TABLE_MAPPERS.keys())


# ---------------------------------------------------------------------------
# build_wysiwyg_table — CNT-90XL
# ---------------------------------------------------------------------------

def test_empty_rows_shows_placeholder():
    tbl = build_wysiwyg_table(CNT90, "A5", [])
    assert tbl.columnCount() == 1
    assert "chưa" in tbl.item(0, 0).text().lower() or "Chưa" in tbl.item(0, 0).text()


def test_unknown_table_id_shows_placeholder():
    rows = [TableRow(key="x", value_measured=1.0, passed=True)]
    tbl = build_wysiwyg_table(CNT90, "Z9", rows)
    assert tbl.columnCount() == 1


def test_a2_sensitivity_columns_and_merge():
    rows = [
        TableRow(key="100kHz", freq_set=100e3, value_measured=12.3, limit="≤ 15 mVrms", passed=True),
        TableRow(key="1MHz", freq_set=1e6, value_measured=13.1, limit="≤ 15 mVrms", passed=True),
        TableRow(key="200MHz", freq_set=200e6, value_measured=20.0, limit="≤ 25 mVrms", passed=True),
    ]
    tbl = build_wysiwyg_table(CNT90, "A2", rows)
    assert tbl.columnCount() == 3
    assert tbl.rowCount() == 3
    assert "mVrms" in tbl.item(0, 1).text()
    # 2 dòng đầu cùng limit -> gộp ô (rowSpan=2), dòng cuối limit khác -> riêng
    assert tbl.rowSpan(0, 2) == 2
    assert tbl.rowSpan(2, 2) == 1
    assert tbl.item(0, 2).text() == "≤ 15 mVrms"
    assert tbl.item(2, 2).text() == "≤ 25 mVrms"


def test_a5_freq_error_columns():
    rows = [
        TableRow(key="5Hz", freq_set=5, value_measured=5.0000012, error=2.4e-7,
                 limit="± 2,4×10⁻⁷", passed=True),
    ]
    tbl = build_wysiwyg_table(CNT90, "A5", rows)
    assert tbl.columnCount() == 4
    assert tbl.rowSpan(0, 3) == 1
    assert tbl.item(0, 3).text() == "± 2,4×10⁻⁷"


def test_a1_oscillator_uses_raw_readings():
    rows = [
        TableRow(key="10MHz", freq_set=10e6, value_measured=10e6 + 1, error=1e-7,
                 limit="± 2,4×10⁻⁷", passed=True,
                 raw_readings=[10e6, 10e6 + 1, 10e6 + 2]),
    ]
    tbl = build_wysiwyg_table(CNT90, "A1", rows)
    assert tbl.rowCount() == 3   # 1 dòng / lần đo thô
    assert tbl.columnCount() == 5
    assert tbl.rowSpan(0, 0) == 3   # cột "Tần số thiết lập" gộp cả 3 dòng


def test_a8_period_error_uses_key_as_label():
    rows = [
        TableRow(key="5 Hz (200 ms)", freq_set=5, value_measured=0.2, error=1e-7,
                 limit="± 2,4×10⁻⁷", passed=True),
    ]
    tbl = build_wysiwyg_table(CNT90, "A8", rows)
    assert tbl.item(0, 0).text() == "5 Hz (200 ms)"


# ---------------------------------------------------------------------------
# Cột checkbox (Bước 2 — rà soát/xác nhận)
# ---------------------------------------------------------------------------

def test_with_checkbox_adds_column_and_toggle_writes_confirmed():
    rows = [
        TableRow(key="5Hz", freq_set=5, value_measured=5.0000012, error=2.4e-7,
                 limit="± 2,4×10⁻⁷", passed=True, confirmed=False),
    ]
    toggled = []
    tbl = build_wysiwyg_table(CNT90, "A5", rows, with_checkbox=True,
                              on_toggle=lambda: toggled.append(1))
    assert tbl.horizontalHeaderItem(0).text() == "Đưa vào\nbáo cáo"
    assert tbl.columnCount() == 5   # 4 cột dữ liệu + 1 cột checkbox
    chk_widget = tbl.cellWidget(0, 0)
    assert chk_widget is not None
    from PyQt5.QtWidgets import QCheckBox
    chk = chk_widget.findChild(QCheckBox)
    chk.setChecked(True)
    assert rows[0].confirmed is True
    assert toggled == [1]


def test_checkbox_spans_all_raw_reading_rows():
    """Bảng kiểu 'đo lặp N lần' (A1) chỉ có 1 TableRow -> checkbox phải gộp
    (span) hết N dòng lưới, không phải chỉ tick được dòng đầu."""
    rows = [
        TableRow(key="10MHz", freq_set=10e6, value_measured=10e6 + 1,
                 raw_readings=[10e6, 10e6 + 1, 10e6 + 2], confirmed=False),
    ]
    tbl = build_wysiwyg_table(CNT90, "A1", rows, with_checkbox=True)
    assert tbl.rowSpan(0, 0) == 3


# ---------------------------------------------------------------------------
# build_wysiwyg_table — NRP2 (chứng minh KHÔNG còn đụng độ mã bảng với CNT-90XL)
# ---------------------------------------------------------------------------

def test_nrp2_a2_has_different_layout_than_cnt90xl_a2():
    """Cùng mã bảng 'A2' nhưng 2 template khác hẳn ý nghĩa cột — đây là bug
    đã tìm thấy (Bước 3 preview NRP2 từng hiển thị nhầm sang layout độ nhạy
    của CNT-90XL) và phải được sửa dứt điểm."""
    cnt90_rows = [
        TableRow(key="100kHz", freq_set=100e3, value_measured=12.3, limit="≤ 15 mVrms"),
    ]
    nrp2_rows = [
        TableRow(key="10MHz", freq_set=10e6, value_measured=-0.05, error=0.05, limit="± 0,1"),
    ]
    tbl_cnt90 = build_wysiwyg_table(CNT90, "A2", cnt90_rows)
    tbl_nrp2 = build_wysiwyg_table(NRP2, "A2", nrp2_rows)

    headers_cnt90 = [tbl_cnt90.horizontalHeaderItem(c).text() for c in range(tbl_cnt90.columnCount())]
    headers_nrp2 = [tbl_nrp2.horizontalHeaderItem(c).text() for c in range(tbl_nrp2.columnCount())]

    assert headers_cnt90 != headers_nrp2
    assert tbl_cnt90.columnCount() == 3       # Tần số/Độ nhạy đo được/Độ nhạy cho phép
    # Tần số/lần1/lần2/lần3/lần4/lần5/TB/Độ KĐBĐ — đúng mẫu Biên Bản (không có Số hiệu chỉnh)
    assert tbl_nrp2.columnCount() == 8
    assert any("nhạy" in h for h in headers_cnt90)
    assert not any("nhạy" in h for h in headers_nrp2)
    assert any("lần" in h for h in headers_nrp2)


def test_nrp2_a1_lan_columns_horizontal():
    """Đúng mẫu Biên Bản: 1 dòng, cột 'lần 1'..'lần 10' nằm ngang (không xếp
    dọc như trước)."""
    rows = [
        TableRow(key="1mW_50MHz", freq_set=50e6, value_measured=0.00099,
                 error=0.00001, limit="± 0,00002",
                 raw_readings=[0.00098, 0.00099, 0.00100], confirmed=False),
    ]
    tbl = build_wysiwyg_table(NRP2, "A1", rows, with_checkbox=True)
    assert tbl.rowCount() == 1
    # 1 (chuẩn) + 10 (lần 1..10) + 1 (Độ KĐBĐ) + 1 (checkbox) = 13
    assert tbl.columnCount() == 13
    assert tbl.item(0, 1).text() == "1 mW"   # cột "Công suất chuẩn" (đã dịch +1 vì checkbox)
    assert tbl.item(0, 2).text() != ""       # lần 1 có giá trị
    assert tbl.item(0, 11) is None or tbl.item(0, 11).text() == ""  # lần 10: không có dữ liệu (chỉ 3 lần đo trong test)


def test_nrp2_a3_groups_by_frequency():
    rows = [
        TableRow(key="50MHz_-30dBm", freq_set=50e6, value_measured=-30.1, limit="± 0,2",
                 raw_readings=[-30.0, -30.1, -30.1, -30.2, -30.1]),
        TableRow(key="50MHz_-20dBm", freq_set=50e6, value_measured=-20.1, limit="± 0,2",
                 raw_readings=[-20.0, -20.1, -20.1, -20.2, -20.1]),
        TableRow(key="1GHz_-30dBm", freq_set=1e9, value_measured=-30.2, limit="± 0,2",
                 raw_readings=[-30.1, -30.2, -30.2, -30.3, -30.2]),
    ]
    tbl = build_wysiwyg_table(NRP2, "A3", rows)
    # Tần số/Công suất chuẩn/lần1-5/TB/Độ KĐBĐ — đúng mẫu Biên Bản
    assert tbl.columnCount() == 9
    assert tbl.rowSpan(0, 0) == 2   # 2 dòng đầu cùng 50MHz -> gộp
    assert tbl.rowSpan(2, 0) == 1   # dòng 1GHz riêng
    assert tbl.item(0, 1).text() != ""   # công suất chuẩn suy từ row.key
    assert tbl.item(0, 2).text() != ""   # lần 1
    assert tbl.item(0, 7).text() != ""   # TB


def test_unknown_template_falls_back_to_cnt90xl():
    rows = [TableRow(key="5Hz", freq_set=5, value_measured=5.0, limit="x")]
    tbl = build_wysiwyg_table("KHONG_TON_TAI", "A5", rows)
    assert tbl.columnCount() == 4   # vẫn dùng layout CNT-90XL, không crash


# ---------------------------------------------------------------------------
# Cột "Đạt/Không đạt" (combobox, chỉ nội bộ app — không in vào docx)
# ---------------------------------------------------------------------------

from PyQt5.QtWidgets import QComboBox  # noqa: E402


def test_status_column_appended_at_end_with_default_from_passed():
    rows = [
        TableRow(key="5Hz", freq_set=5, value_measured=5.0000012, error=2.4e-7,
                 limit="± 2,4×10⁻⁷", passed=True),
    ]
    tbl = build_wysiwyg_table(CNT90, "A5", rows, with_status=True)
    assert tbl.columnCount() == 5   # 4 cột dữ liệu + 1 status
    assert tbl.horizontalHeaderItem(4).text() == "Đạt/\nKhông đạt"
    combo = tbl.cellWidget(0, 4)
    assert isinstance(combo, QComboBox)
    assert combo.currentIndex() == 1   # passed=True -> "✅ Đạt"


def test_status_column_defaults_to_dash_when_passed_none():
    rows = [TableRow(key="10MHz", freq_set=10e6, value_measured=12.3, limit="≤ 15 mVrms", passed=None)]
    tbl = build_wysiwyg_table(CNT90, "A2", rows, with_status=True)
    combo = tbl.cellWidget(0, tbl.columnCount() - 1)
    assert combo.currentIndex() == 0   # "—"


def test_status_combobox_writes_back_to_passed_and_calls_callback():
    rows = [TableRow(key="5Hz", freq_set=5, value_measured=5.0, limit="x", passed=None)]
    changed = []
    tbl = build_wysiwyg_table(CNT90, "A5", rows, with_status=True,
                              on_status_change=lambda: changed.append(1))
    combo = tbl.cellWidget(0, tbl.columnCount() - 1)
    combo.setCurrentIndex(2)   # "❌ Không đạt"
    assert rows[0].passed is False
    assert changed == [1]
    combo.setCurrentIndex(1)   # "✅ Đạt"
    assert rows[0].passed is True


def test_checkbox_and_status_together_correct_order():
    """Khi bật cả 2: [checkbox][...dữ liệu...][status]."""
    rows = [TableRow(key="5Hz", freq_set=5, value_measured=5.0, limit="x", passed=True, confirmed=False)]
    tbl = build_wysiwyg_table(CNT90, "A5", rows, with_checkbox=True, with_status=True)
    # 4 cột dữ liệu + checkbox (đầu) + status (cuối) = 6
    assert tbl.columnCount() == 6
    assert tbl.horizontalHeaderItem(0).text() == "Đưa vào\nbáo cáo"
    assert tbl.horizontalHeaderItem(5).text() == "Đạt/\nKhông đạt"
    from PyQt5.QtWidgets import QCheckBox
    assert tbl.cellWidget(0, 0).findChild(QCheckBox) is not None
    assert isinstance(tbl.cellWidget(0, 5), QComboBox)


def test_status_column_spans_all_raw_reading_rows():
    """Bảng kiểu A1 (nhiều dòng lưới, 1 TableRow) -> combobox cũng phải gộp
    (span) hết N dòng, giống hệt checkbox."""
    rows = [
        TableRow(key="10MHz", freq_set=10e6, value_measured=10e6 + 1,
                 raw_readings=[10e6, 10e6 + 1, 10e6 + 2], passed=None),
    ]
    tbl = build_wysiwyg_table(CNT90, "A1", rows, with_status=True)
    assert tbl.rowSpan(0, tbl.columnCount() - 1) == 3


def test_nrp2_status_column_also_appended():
    """NRP2 A1 là 1 dòng duy nhất (lần 1..10 nằm ngang thành cột, không xếp
    dọc như CNT-90XL) -> chỉ cần combobox ở dòng đó, không cần gộp span."""
    rows = [
        TableRow(key="1mW_50MHz", freq_set=50e6, value_measured=0.00099,
                 raw_readings=[0.00098, 0.00099, 0.00100], passed=None),
    ]
    tbl = build_wysiwyg_table(NRP2, "A1", rows, with_status=True)
    assert tbl.rowCount() == 1
    assert tbl.horizontalHeaderItem(tbl.columnCount() - 1).text() == "Đạt/\nKhông đạt"
    assert isinstance(tbl.cellWidget(0, tbl.columnCount() - 1), QComboBox)
