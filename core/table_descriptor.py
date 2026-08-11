"""
core/table_descriptor.py
=========================
Schema mô tả 1 bảng báo cáo dưới dạng dữ liệu (JSON) thay vì code Python
viết tay — nền tảng để thêm 1 bảng/mẫu báo cáo mới không cần lập trình viên
sửa code (xem core/table_engine.py cho phần đọc và áp dụng descriptor này,
core/report_templates/generic.py cho lớp template data-driven dùng chung).

Thuần Python, không phụ thuộc Qt/docx → test độc lập.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# Các giá trị hợp lệ cho từng enum-string — dùng để validate rõ ràng khi load.
VALID_ROLES = {
    "freq_set", "measured", "error", "limit", "raw_reading_index", "free_text",
    "power_from_key",  # NRP2 A3: parse "50MHz_-30dBm" -> -30.0 (giữ đúng cơ chế gốc)
}
VALID_FORMATS = {
    "freq", "hz_measured", "period", "mv", "dbm", "w", "sci", "sci_signed",
    "correction_mw", "correction_db", "text",
    # Biến thể không kèm đơn vị (xem core/table_engine.py::_FORMATTERS) — cùng
    # cách làm tròn/định dạng số như bản gốc, chỉ bỏ chữ đơn vị suffix.
    "freq_no_unit", "hz_measured_no_unit", "period_no_unit", "mv_no_unit",
    "dbm_no_unit", "w_no_unit", "correction_mw_no_unit", "correction_db_no_unit",
}
VALID_SCOPES = {"row", "table"}
VALID_LAYOUTS = {"repeated_rows", "raw_expand_vertical", "raw_expand_horizontal"}
VALID_MERGE_MODES = {"constant", "grouped"}
VALID_PASS_RULE_TYPES = {
    "relative_error_vs_fixed_limit", "value_vs_parsed_threshold",
    "correction_vs_reference", "none",
}


@dataclass
class RowDef:
    key: str                              # định danh ngắn, dùng cho dropdown "chọn dòng đích" (Scenario Builder)
    freq_set: Optional[float] = None      # -> TableRow.freq_set (hiển thị/format freq_str, KHÔNG nhất thiết dùng trong công thức)
    reference: Optional[float] = None     # giá trị "chuẩn" dùng trong công thức pass_rule (freq_set/period_set/power_set — có thể khác freq_set, vd A8: period_set)
    raw_count: Optional[int] = None       # số giá trị report_val tiêu thụ cho dòng này; None = lấy hết còn lại
    limit: str = ""                       # chỉ dùng khi pass_rule=value_vs_parsed_threshold
    display_label: str = ""               # override `key` khi hiển thị trong báo cáo (vd A8: "5 Hz (200 ms)")
    measured_count: Optional[int] = None  # số phần tử ĐẦU của raw_readings dùng để tính value_measured/
                                           # error/passed (core/table_engine.py::apply_pass_rule) — phần
                                           # CÒN LẠI là giá trị kịch bản TỰ TÍNH SẴN (vd sai số) chỉ để
                                           # hiển thị lại đúng những gì đã đẩy, KHÔNG dùng lại trong công
                                           # thức (phần mềm tính error/passed độc lập, không đọc lại các
                                           # slot này). None (mặc định) = dùng HẾT raw_readings (hành vi
                                           # cũ, mọi bảng không cần nhiều field/dòng).
    value_format_seq: Optional[list] = None  # định dạng riêng cho TỪNG report_val() liên tiếp của 1 dòng
                                              # (vd A5: ["hz_measured", "sci"] = giá trị đo rồi đến sai số
                                              # đã tính sẵn) — độ dài PHẢI khớp raw_count. None (mặc định)
                                              # = mọi report_val() của bảng dùng chung descriptor.value_format
                                              # (hành vi cũ).
    uncertainty_index: Optional[int] = None  # vị trí (0-based) trong raw_readings chứa Độ KĐBĐ kịch bản
                                              # TỰ TÍNH rồi đẩy thêm (vd QTHC 2.515 — Độ KĐBĐ không tính
                                              # được từ công thức, phải do kỹ sư hiệu chuẩn tự nhập theo
                                              # ngân sách bất định của họ) — core/table_engine.py::
                                              # apply_pass_rule ghi giá trị đã định dạng (theo
                                              # value_format_seq[uncertainty_index]) vào TableRow.limit, để
                                              # GCN (gcn_limit()) đọc lại được ĐÚNG giá trị này (không chỉ
                                              # report_val() ở Biên Bản). None (mặc định) = không có cột
                                              # Độ KĐBĐ nào cần lộ ra ngoài report_val().

    @classmethod
    def from_dict(cls, d: dict) -> "RowDef":
        return cls(
            key=d["key"],
            freq_set=d.get("freq_set"),
            reference=d.get("reference"),
            raw_count=d.get("raw_count"),
            limit=d.get("limit", ""),
            display_label=d.get("display_label", ""),
            measured_count=d.get("measured_count"),
            value_format_seq=d.get("value_format_seq"),
            uncertainty_index=d.get("uncertainty_index"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ColumnDef:
    role: str            # freq_set | measured | error | limit | raw_reading_index | free_text
    format: str           # freq | hz_measured | period | mv | dbm | w | sci | sci_signed | correction_mw | correction_db | text
    jinja_field: str      # tên field trong dict Jinja (phải khớp đúng tag đã viết trong file .docx mẫu)
    scope: str = "row"    # "row" (tables.X.rows[i].<field>) | "table" (tables.X.<field>)
    col: Optional[int] = None  # cột vật lý 0-based trong docx — chỉ cần khi cột này nằm trong merge spec

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnDef":
        return cls(
            role=d["role"], format=d["format"], jinja_field=d["jinja_field"],
            scope=d.get("scope", "row"), col=d.get("col"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MergeSpec:
    col: int
    mode: str                # "constant" -> gộp cả cột thành 1 ô | "grouped" -> gộp các dòng liên tiếp cùng key_field
    value_field: str = ""    # mode=constant: field (table-scope) để ghi vào ô đã gộp
    key_field: str = ""      # mode=grouped: field (row-scope) dùng so sánh để nhóm
    text_field: str = ""     # mode=grouped: field (row-scope) hiển thị của dòng đầu nhóm

    @classmethod
    def from_dict(cls, d: dict) -> "MergeSpec":
        return cls(
            col=d["col"], mode=d["mode"],
            value_field=d.get("value_field", ""),
            key_field=d.get("key_field", ""),
            text_field=d.get("text_field", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TableDescriptor:
    schema_version: int
    table_id: str
    name: str
    order: int
    scenario_file: str = ""            # tên file trong scenarios/<subdir>/, "" nếu chưa gán
    layout: str = "repeated_rows"      # repeated_rows | raw_expand_vertical | raw_expand_horizontal
    value_unit: str = ""               # -> TableRow.value_unit ("Hz","mVrms","dBm","s","W"...)
    value_format: str = "text"         # 1 trong VALID_FORMATS — dùng cho report_val()/report_raw()
                                        # (core/table_engine.py::build_cursor_context), KHÔNG phải/cột
    rows: list = field(default_factory=list)       # list[RowDef]
    columns: list = field(default_factory=list)    # list[ColumnDef]
    pass_rule: dict = field(default_factory=lambda: {"type": "none"})
    merge: list = field(default_factory=list)      # list[MergeSpec]
    gcn: Optional[dict] = None         # {"param_name": str, "limit_str": str} — chỉ CNT90XL GCN

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "table_id": self.table_id,
            "name": self.name,
            "order": self.order,
            "scenario_file": self.scenario_file,
            "layout": self.layout,
            "value_unit": self.value_unit,
            "value_format": self.value_format,
            "rows": [r.to_dict() for r in self.rows],
            "columns": [c.to_dict() for c in self.columns],
            "pass_rule": self.pass_rule,
            "merge": [m.to_dict() for m in self.merge],
            "gcn": self.gcn,
        }


def validate_descriptor(d: TableDescriptor) -> list:
    """Kiểm tra 1 TableDescriptor đã dựng trong bộ nhớ (chưa/đã ghi file đều
    được) — trả về danh sách lỗi dạng chuỗi (rỗng = hợp lệ). Dùng chung bởi
    _validate() (khi load từ JSON) và bởi GUI sửa trực tiếp (gui/
    template_manager_dialog.py::TableDetailDialog) để chặn lưu dữ liệu sai
    TRƯỚC khi ghi đè file."""
    errs = []
    if d.layout not in VALID_LAYOUTS:
        errs.append(f"layout '{d.layout}' không hợp lệ")
    if d.value_format not in VALID_FORMATS:
        errs.append(f"value_format '{d.value_format}' không hợp lệ")
    if d.pass_rule.get("type") not in VALID_PASS_RULE_TYPES:
        errs.append(f"pass_rule.type '{d.pass_rule.get('type')}' không hợp lệ")
    for c in d.columns:
        if c.role not in VALID_ROLES:
            errs.append(f"column role '{c.role}' không hợp lệ")
        if c.format not in VALID_FORMATS:
            errs.append(f"column format '{c.format}' không hợp lệ")
        if c.scope not in VALID_SCOPES:
            errs.append(f"column scope '{c.scope}' không hợp lệ")
    for m in d.merge:
        if m.mode not in VALID_MERGE_MODES:
            errs.append(f"merge mode '{m.mode}' không hợp lệ")
    for r in d.rows:
        if r.value_format_seq is not None:
            bad = [f for f in r.value_format_seq if f not in VALID_FORMATS]
            if bad:
                errs.append(f"dòng '{r.key}': value_format_seq có định dạng không hợp lệ {bad}")
            if r.raw_count is not None and len(r.value_format_seq) != r.raw_count:
                errs.append(f"dòng '{r.key}': value_format_seq (len={len(r.value_format_seq)}) "
                            f"phải khớp raw_count ({r.raw_count})")
            if r.measured_count is not None and r.measured_count > len(r.value_format_seq):
                errs.append(f"dòng '{r.key}': measured_count ({r.measured_count}) vượt quá "
                             f"số phần tử value_format_seq ({len(r.value_format_seq)})")
    if not d.rows:
        errs.append("thiếu 'rows' (bảng phải có ít nhất 1 dòng định nghĩa)")
    return errs


def _validate(d: TableDescriptor, path: Path) -> None:
    errs = validate_descriptor(d)
    if errs:
        raise ValueError(f"{path}: " + "; ".join(errs))


def load_table_descriptor(path: Path) -> TableDescriptor:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        d = TableDescriptor(
            schema_version=raw["schema_version"],
            table_id=raw["table_id"],
            name=raw["name"],
            order=raw["order"],
            scenario_file=raw.get("scenario_file", ""),
            layout=raw.get("layout", "repeated_rows"),
            value_unit=raw.get("value_unit", ""),
            value_format=raw.get("value_format", "text"),
            rows=[RowDef.from_dict(r) for r in raw.get("rows", [])],
            columns=[ColumnDef.from_dict(c) for c in raw.get("columns", [])],
            pass_rule=raw.get("pass_rule", {"type": "none"}),
            merge=[MergeSpec.from_dict(m) for m in raw.get("merge", [])],
            gcn=raw.get("gcn"),
        )
    except KeyError as exc:
        raise ValueError(f"{path}: thiếu trường bắt buộc {exc}") from exc
    _validate(d, path)
    return d


def load_table_descriptors(tables_dir: Path) -> list:
    """Đọc mọi *.json trong tables_dir, trả về danh sách TableDescriptor đã
    sort theo .order. Thư mục không tồn tại -> trả về [] (template chưa có
    bảng nào định nghĩa qua descriptor)."""
    if not tables_dir.exists():
        return []
    descriptors = [load_table_descriptor(p) for p in sorted(tables_dir.glob("*.json"))]
    descriptors.sort(key=lambda d: d.order)
    return descriptors
