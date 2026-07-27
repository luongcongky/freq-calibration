"""
unit_test/test_report_preview.py
=================================
Test cho:
  - core.result_mapper.TABLE_ROW_KEYS / TABLE_FIELD_KEYS (metadata cho dropdown
    gắn report_tag trong Scenario Builder).
  - gui.report_preview.build_wysiwyg_table (bảng preview khớp layout docx thật).
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication

from core.result_mapper import TABLE_MAPPERS, TABLE_ROW_KEYS, TABLE_FIELD_KEYS
from core.session import TableRow
from gui.report_preview import build_wysiwyg_table

_app = QApplication.instance() or QApplication([])


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
# build_wysiwyg_table
# ---------------------------------------------------------------------------

def test_empty_rows_shows_placeholder():
    tbl = build_wysiwyg_table("A5", [])
    assert tbl.columnCount() == 1
    assert "chưa" in tbl.item(0, 0).text().lower() or "Chưa" in tbl.item(0, 0).text()


def test_unknown_table_id_shows_placeholder():
    rows = [TableRow(key="x", value_measured=1.0, passed=True)]
    tbl = build_wysiwyg_table("Z9", rows)
    assert tbl.columnCount() == 1


def test_a2_sensitivity_columns_and_merge():
    rows = [
        TableRow(key="100kHz", freq_set=100e3, value_measured=12.3, limit="≤ 15 mVrms", passed=True),
        TableRow(key="1MHz", freq_set=1e6, value_measured=13.1, limit="≤ 15 mVrms", passed=True),
        TableRow(key="200MHz", freq_set=200e6, value_measured=20.0, limit="≤ 25 mVrms", passed=True),
    ]
    tbl = build_wysiwyg_table("A2", rows)
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
    tbl = build_wysiwyg_table("A5", rows)
    assert tbl.columnCount() == 4
    assert tbl.rowSpan(0, 3) == 1
    assert tbl.item(0, 3).text() == "± 2,4×10⁻⁷"


def test_a1_oscillator_uses_raw_readings():
    rows = [
        TableRow(key="10MHz", freq_set=10e6, value_measured=10e6 + 1, error=1e-7,
                 limit="± 2,4×10⁻⁷", passed=True,
                 raw_readings=[10e6, 10e6 + 1, 10e6 + 2]),
    ]
    tbl = build_wysiwyg_table("A1", rows)
    assert tbl.rowCount() == 3   # 1 dòng / lần đo thô
    assert tbl.columnCount() == 5
    assert tbl.rowSpan(0, 0) == 3   # cột "Tần số thiết lập" gộp cả 3 dòng


def test_a8_period_error_uses_key_as_label():
    rows = [
        TableRow(key="5 Hz (200 ms)", freq_set=5, value_measured=0.2, error=1e-7,
                 limit="± 2,4×10⁻⁷", passed=True),
    ]
    tbl = build_wysiwyg_table("A8", rows)
    assert tbl.item(0, 0).text() == "5 Hz (200 ms)"
