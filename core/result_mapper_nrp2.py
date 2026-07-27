"""
core/result_mapper_nrp2.py
===========================
Chuyển StepResult (từ ScenarioRunner) sang ReportTable cho template
QTHC 2.515:2021 (máy đo công suất NRP2) — TÁCH RIÊNG khỏi
core/result_mapper.py vì cả 2 template đều dùng mã bảng "A1"/"A2"/"A3" và
không được dùng chung 1 dict TABLE_MAPPERS (sẽ áp nhầm hàm map của
CNT-90XL cho dữ liệu NRP2).

QTHC 2.515:2021 là văn bản HIỆU CHUẨN (báo cáo giá trị + số hiệu chỉnh +
độ không đảm bảo đo), không phải KIỂM ĐỊNH (đạt/không đạt) như QTKĐ 2.461 —
nên mọi TableRow ở đây luôn có passed=None, limit="" (không có ngưỡng); field
`error` được dùng lại với ý nghĩa "Số hiệu chỉnh" (giá trị chuẩn − giá trị
đo trung bình), không phải sai số tương đối.

Không phụ thuộc Qt/docx → test được độc lập.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from core.session import TableRow, ReportTable

# ---------------------------------------------------------------------------
# Định nghĩa 3 bảng theo đúng QTHC 2.515:2021
# ---------------------------------------------------------------------------

# Bảng A1 (mục 5.3.1) — đầu ra chuẩn NRP2: 1 điểm 1mW @ 50MHz, đo 10 lần trên NRVD.
_TABLE_A1_ROWS = [
    ("1mW_50MHz", 50e6, 1e-3),   # (row_key, freq_hz, power_set_w)
]

# Bảng A2 (mục 5.3.2) — độ chính xác đo mức công suất tuyệt đối tại 0 dBm,
# 13 điểm tần số.
_TABLE_A2_ROWS = [
    ("10MHz", 10e6), ("50MHz", 50e6), ("500MHz", 500e6),
    ("1GHz", 1e9), ("5GHz", 5e9), ("10GHz", 10e9), ("15GHz", 15e9),
    ("20GHz", 20e9), ("25GHz", 25e9), ("30GHz", 30e9), ("35GHz", 35e9),
    ("40GHz", 40e9), ("49GHz", 49e9),
]
_A2_POWER_SET_DBM = 0.0

# Bảng A3 (mục 5.3.3) — độ chính xác đo công suất qua NRPC50 calibration kit:
# 8 tần số × 6 mức công suất mỗi tần số.
_A3_FREQS = [("50MHz", 50e6), ("1GHz", 1e9), ("5GHz", 5e9), ("10GHz", 10e9),
             ("20GHz", 20e9), ("30GHz", 30e9), ("40GHz", 40e9), ("49GHz", 49e9)]
_A3_POWERS_DBM = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0]
_TABLE_A3_ROWS = [
    (f"{flabel}_{int(p)}dBm", fhz, p)
    for flabel, fhz in _A3_FREQS
    for p in _A3_POWERS_DBM
]


# ---------------------------------------------------------------------------
# Helper gom StepResult theo report_tag (giống result_mapper.py, thuần generic)
# ---------------------------------------------------------------------------

def _group_tagged(step_results) -> dict:
    groups: dict = defaultdict(list)
    for r in step_results:
        tag = getattr(r, "report_tag", None)
        if not tag:
            continue
        key = (tag.get("table", ""), tag.get("row_key", ""), tag.get("field", ""))
        groups[key].append(r)
    return groups


def _last_ok_value(groups: dict, table: str, row_key: str, field: str) -> Optional[float]:
    items = groups.get((table, row_key, field), [])
    ok = [r for r in items if r.ok and r.value is not None]
    return ok[-1].value if ok else None


def _all_ok_values(groups: dict, table: str, row_key: str, field: str) -> list:
    items = groups.get((table, row_key, field), [])
    return [r.value for r in items if r.ok and r.value is not None]


def _fmt_uncertainty(u: Optional[float]) -> str:
    """QTHC 2.515 không có khái niệm 'giới hạn' — tái dùng TableRow.limit
    (chuỗi tự do) để chứa Độ không đảm bảo đo mở rộng (U, k=2) thay vì
    ngưỡng đạt/không đạt."""
    if u is None:
        return ""
    return f"± {u:.4g}"


# ---------------------------------------------------------------------------
# Mapping từng bảng
# ---------------------------------------------------------------------------

def map_table_a1(groups: dict) -> ReportTable:
    rows = []
    for row_key, freq_hz, power_set_w in _TABLE_A1_ROWS:
        raws = _all_ok_values(groups, "A1", row_key, "raw_reading")
        p_avg = _last_ok_value(groups, "A1", row_key, "power_measured")
        if raws and p_avg is None:
            p_avg = sum(raws) / len(raws)
        correction = (power_set_w - p_avg) if p_avg is not None else None
        uncertainty = _last_ok_value(groups, "A1", row_key, "uncertainty")
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="W",
            error=correction, limit=_fmt_uncertainty(uncertainty), passed=None,
            raw_readings=raws,
        ))
    return ReportTable(table_id="A1",
                       name="Xác định độ chính xác mức công suất tại đầu ra chuẩn",
                       rows=rows, passed=None)


def map_table_a2(groups: dict) -> ReportTable:
    rows = []
    for row_key, freq_hz in _TABLE_A2_ROWS:
        p_avg = _last_ok_value(groups, "A2", row_key, "power_measured")
        correction = (_A2_POWER_SET_DBM - p_avg) if p_avg is not None else None
        uncertainty = _last_ok_value(groups, "A2", row_key, "uncertainty")
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="dBm",
            error=correction, limit=_fmt_uncertainty(uncertainty), passed=None,
        ))
    return ReportTable(table_id="A2",
                       name="Xác định độ chính xác đo mức công suất tuyệt đối (tại 0 dBm)",
                       rows=rows, passed=None)


def map_table_a3(groups: dict) -> ReportTable:
    rows = []
    for row_key, freq_hz, power_set_dbm in _TABLE_A3_ROWS:
        p_avg = _last_ok_value(groups, "A3", row_key, "power_measured")
        correction = (power_set_dbm - p_avg) if p_avg is not None else None
        uncertainty = _last_ok_value(groups, "A3", row_key, "uncertainty")
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="dBm",
            error=correction, limit=_fmt_uncertainty(uncertainty), passed=None,
        ))
    return ReportTable(table_id="A3",
                       name="Xác định độ chính xác đo công suất với bộ hiệu chuẩn "
                            "công suất NRPC50 calibration kit",
                       rows=rows, passed=None)


TABLE_MAPPERS_NRP2 = {
    "A1": map_table_a1,
    "A2": map_table_a2,
    "A3": map_table_a3,
}


def map_results_nrp2(table_id: str, step_results: list) -> Optional[ReportTable]:
    """
    Chuyển danh sách StepResult của một bài test NRP2 sang ReportTable.

    table_id : "A1" | "A2" | "A3"
    step_results : list[StepResult] (từ ScenarioRunner.run())
    """
    mapper = TABLE_MAPPERS_NRP2.get(table_id)
    if mapper is None:
        return None
    groups = _group_tagged(step_results)
    return mapper(groups)
