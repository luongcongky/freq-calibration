"""
unit_test/test_table_descriptor.py
=====================================
Test schema TableDescriptor (core/table_descriptor.py) — tập trung vào
field `value_format` mới thêm (dùng cho report_val()/report_raw() trong
core/table_engine.py::build_cursor_context).
"""

import json
from pathlib import Path

import pytest

from core.table_descriptor import RowDef, TableDescriptor, load_table_descriptor


def _minimal_descriptor(**overrides) -> TableDescriptor:
    kwargs = dict(
        schema_version=1, table_id="A9", name="Bảng thử", order=1,
        rows=[RowDef(key="row1")],
    )
    kwargs.update(overrides)
    return TableDescriptor(**kwargs)


def test_value_format_defaults_to_text():
    d = _minimal_descriptor()
    assert d.value_format == "text"


def test_value_format_missing_in_json_defaults_to_text(tmp_path):
    """Descriptor JSON của 2 template cũ (CNT90XL/NRP2) không có key này."""
    raw = _minimal_descriptor().to_dict()
    del raw["value_format"]
    path = tmp_path / "A9.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_table_descriptor(path)
    assert loaded.value_format == "text"


def test_value_format_roundtrip(tmp_path):
    d = _minimal_descriptor(value_format="dbm")
    path = tmp_path / "A9.json"
    path.write_text(json.dumps(d.to_dict()), encoding="utf-8")
    loaded = load_table_descriptor(path)
    assert loaded.value_format == "dbm"


def test_invalid_value_format_raises(tmp_path):
    d = _minimal_descriptor(value_format="bogus")
    path = tmp_path / "A9.json"
    path.write_text(json.dumps(d.to_dict()), encoding="utf-8")
    with pytest.raises(ValueError, match="value_format"):
        load_table_descriptor(path)
