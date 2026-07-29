"""
core/result_mapper.py
=====================
Chuyển đổi danh sách StepResult (thô từ ScenarioRunner) sang các ReportTable
có cấu trúc (TableRow theo từng bảng A1–A8 của QTKĐ).

Kịch bản đẩy giá trị vào báo cáo bằng action "report_val" (chỉ 1 tham số
value — không cần khai bảng đích, vì 1 lần chạy kịch bản luôn ứng với đúng
1 bài test/1 bảng, table_id đã được biết từ bên ngoài khi gọi map_results).
ResultMapper LẤY TUẦN TỰ (theo đúng thứ tự StepResult được tạo ra, tức đúng
thứ tự thực thi kịch bản — kể cả trong Loop) mọi giá trị report_val, rồi
tách theo số giá trị/dòng đã định nghĩa sẵn cho từng bảng để đổ vào từng
TableRow theo đúng thứ tự dòng của bảng.

Không phụ thuộc Qt và không phụ thuộc report_generator → test được độc lập.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.session import TableRow, ReportTable

log = logging.getLogger(__name__)

# Giới hạn sai số cho phép theo QTKĐ 2.461 : 2018
_FREQ_LIMIT = 2.4e-7      # ± 2,4×10⁻⁷ (tần số + chu kỳ + dao động thạch anh)

# Định nghĩa từng bảng: table_id, name, các hàng (row_key, freq_Hz, limit_str)
_TABLE_A1_ROWS = [
    ("10MHz", 10e6),
]

_TABLE_A2_ROWS = [  # Độ nhạy kênh A (mVrms)
    ("100kHz", 100e3, "≤ 15 mVrms"),
    ("1MHz",   1e6,   "≤ 15 mVrms"),
    ("10MHz",  10e6,  "≤ 15 mVrms"),
    ("25MHz",  25e6,  "≤ 15 mVrms"),
    ("40MHz",  40e6,  "≤ 15 mVrms"),
    ("60MHz",  60e6,  "≤ 15 mVrms"),
    ("80MHz",  80e6,  "≤ 15 mVrms"),
    ("100MHz", 100e6, "≤ 15 mVrms"),
    ("150MHz", 150e6, "≤ 15 mVrms"),
    ("200MHz", 200e6, "≤ 25 mVrms"),
    ("250MHz", 250e6, "≤ 25 mVrms"),
    ("300MHz", 300e6, "≤ 25 mVrms"),
]

_TABLE_A3_ROWS = _TABLE_A2_ROWS   # Kênh B giống kênh A

_TABLE_A4_ROWS = [  # Độ nhạy kênh C (dBm)
    ("400MHz",  400e6,  "≤ -27 dBm"),
    ("1GHz",    1e9,    "≤ -27 dBm"),
    ("2GHz",    2e9,    "≤ -27 dBm"),
    ("5GHz",    5e9,    "≤ -27 dBm"),
    ("10GHz",   10e9,   "≤ -27 dBm"),
    ("13GHz",   13e9,   "≤ -27 dBm"),
    ("16GHz",   16e9,   "≤ -27 dBm"),
    ("18GHz",   18e9,   "≤ -29 dBm"),
    ("19.9GHz", 19.9e9, "≤ -29 dBm"),
    ("20GHz",   20e9,   "≤ -27 dBm"),
    ("22GHz",   22e9,   "≤ -27 dBm"),
]

_TABLE_A5_ROWS = [  # Sai số tần số kênh A
    ("5Hz",    5),
    ("10Hz",   10),
    ("100Hz",  100),
    ("1kHz",   1e3),
    ("10kHz",  10e3),
    ("100kHz", 100e3),
    ("500kHz", 500e3),
    ("1MHz",   1e6),
    ("10MHz",  10e6),
    ("100MHz", 100e6),
    ("300MHz", 300e6),
]

_TABLE_A6_ROWS = _TABLE_A5_ROWS   # Kênh B giống kênh A

_TABLE_A7_ROWS = [  # Sai số tần số kênh C
    ("400MHz", 400e6),
    ("1GHz",   1e9),
    ("2GHz",   2e9),
    ("3GHz",   3e9),
]

_TABLE_A8_ROWS = [  # Sai số đo chu kỳ (key, tần số Hz, chu kỳ s, label hiển thị)
    ("5Hz",    5,      0.2,     "5 Hz (200 ms)"),
    ("10Hz",   10,     0.1,     "10 Hz (100 ms)"),
    ("100Hz",  100,    0.01,    "100 Hz (10 ms)"),
    ("1kHz",   1e3,    1e-3,    "1 kHz (1 ms)"),
    ("10kHz",  10e3,   100e-6,  "10 kHz (100 µs)"),
    ("100kHz", 100e3,  10e-6,   "100 kHz (10 µs)"),
    ("1MHz",   1e6,    1e-6,    "1 MHz (1 µs)"),
    ("2MHz",   2e6,    0.5e-6,  "2 MHz (0,5 µs)"),
    ("10MHz",  10e6,   100e-9,  "10 MHz (100 ns)"),
    ("50MHz",  50e6,   20e-9,   "50 MHz (20 ns)"),
    ("100MHz", 100e6,  10e-9,   "100 MHz (10 ns)"),
    ("200MHz", 200e6,  5e-9,    "200 MHz (5 ns)"),
    ("300MHz", 300e6,  3.33e-9, "300 MHz (3,33 ns)"),
]


def _table_values(step_results) -> list:
    """Lấy TUẦN TỰ (đúng thứ tự thực thi) mọi giá trị report_val — step_results
    của 1 bài test luôn chỉ ứng với đúng 1 bảng, không cần lọc theo tên bảng."""
    return [r.value for r in step_results
            if r.action == "report_val" and r.ok and r.value is not None]


def _consume(values: list, n: Optional[int]) -> tuple:
    """Lấy n phần tử đầu (n=None -> lấy hết); trả (chunk, phần còn lại)."""
    if n is None:
        return values, []
    return values[:n], values[n:]


def _leftover_note(table_id: str, leftover: list) -> str:
    if not leftover:
        return ""
    return (f"Kịch bản đẩy dư {len(leftover)} giá trị report_val cho bảng "
            f"{table_id} không dùng tới — kiểm tra lại kịch bản.")


# ---------------------------------------------------------------------------
# Mapping từng bảng
# ---------------------------------------------------------------------------

def map_table_a1(step_results) -> ReportTable:
    """Bảng A1 — Sai số tần số bộ dao động thạch anh (10 MHz)."""
    values = _table_values(step_results)
    rows = []
    table_passed = True
    for row_key, freq_set in _TABLE_A1_ROWS:
        raws, values = _consume(values, None)   # 1 dòng duy nhất -> lấy hết
        f_avg = sum(raws) / len(raws) if raws else None
        delta_f = abs(f_avg - freq_set) / freq_set if f_avg is not None else None

        passed = delta_f is not None and abs(delta_f) <= _FREQ_LIMIT
        if delta_f is not None and not passed:
            table_passed = False

        rows.append(TableRow(
            key=row_key,
            freq_set=freq_set,
            value_measured=f_avg,
            value_unit="Hz",
            error=delta_f,
            limit="± 2,4×10⁻⁷",
            passed=passed if delta_f is not None else None,
            raw_readings=raws,
        ))

    return ReportTable(table_id="A1",
                       name="Xác định sai số tần số bộ dao động thạch anh",
                       rows=rows,
                       passed=table_passed if rows else None,
                       note=_leftover_note("A1", values))


def _map_sensitivity_table(table_id: str, name: str, row_defs: list,
                            step_results) -> ReportTable:
    """Dùng chung cho A2 (kênh A), A3 (kênh B) — 1 giá trị (mVrms)/dòng."""
    values = _table_values(step_results)
    rows = []
    table_passed = True
    for row_key, freq_set, limit_str in row_defs:
        chunk, values = _consume(values, 1)
        sens_mv = chunk[0] if chunk else None

        limit_mv = 15.0 if "15" in limit_str else 25.0
        passed = sens_mv is not None and sens_mv <= limit_mv
        if sens_mv is not None and not passed:
            table_passed = False

        rows.append(TableRow(
            key=row_key,
            freq_set=freq_set,
            value_measured=sens_mv,
            value_unit="mVrms",
            error=None,
            limit=limit_str,
            passed=passed if sens_mv is not None else None,
        ))
    return ReportTable(table_id=table_id, name=name, rows=rows,
                       passed=table_passed if rows else None,
                       note=_leftover_note(table_id, values))


def map_table_a2(step_results) -> ReportTable:
    return _map_sensitivity_table(
        "A2", "Xác định độ nhạy đầu vào kênh A", _TABLE_A2_ROWS, step_results)


def map_table_a3(step_results) -> ReportTable:
    return _map_sensitivity_table(
        "A3", "Xác định độ nhạy đầu vào kênh B", _TABLE_A3_ROWS, step_results)


def map_table_a4(step_results) -> ReportTable:
    """Bảng A4 — Độ nhạy kênh C (dBm), 1 giá trị/dòng."""
    values = _table_values(step_results)
    rows = []
    table_passed = True
    for row_key, freq_set, limit_str in _TABLE_A4_ROWS:
        chunk, values = _consume(values, 1)
        sens_dbm = chunk[0] if chunk else None
        limit_dbm = float(limit_str.replace("≤ ", "").replace(" dBm", ""))
        passed = sens_dbm is not None and sens_dbm <= limit_dbm
        if sens_dbm is not None and not passed:
            table_passed = False
        rows.append(TableRow(
            key=row_key,
            freq_set=freq_set,
            value_measured=sens_dbm,
            value_unit="dBm",
            error=None,
            limit=limit_str,
            passed=passed if sens_dbm is not None else None,
        ))
    return ReportTable(table_id="A4", name="Xác định độ nhạy đầu vào kênh C",
                       rows=rows, passed=table_passed if rows else None,
                       note=_leftover_note("A4", values))


def _map_freq_error_table(table_id: str, name: str, row_defs: list,
                           step_results) -> ReportTable:
    """Dùng chung cho A5 (kênh A), A6 (kênh B), A7 (kênh C) — 1 giá trị/dòng
    (tần số đo được); sai số đo tự tính từ tần số thiết lập của dòng đó."""
    values = _table_values(step_results)
    rows = []
    table_passed = True
    for row_key, freq_set in row_defs:
        chunk, values = _consume(values, 1)
        f_meas = chunk[0] if chunk else None
        delta_f = abs(f_meas - freq_set) / freq_set if f_meas is not None else None

        passed = delta_f is not None and abs(delta_f) <= _FREQ_LIMIT
        if delta_f is not None and not passed:
            table_passed = False

        rows.append(TableRow(
            key=row_key,
            freq_set=freq_set,
            value_measured=f_meas,
            value_unit="Hz",
            error=delta_f,
            limit="± 2,4×10⁻⁷",
            passed=passed if delta_f is not None else None,
        ))
    return ReportTable(table_id=table_id, name=name, rows=rows,
                       passed=table_passed if rows else None,
                       note=_leftover_note(table_id, values))


def map_table_a5(step_results) -> ReportTable:
    return _map_freq_error_table(
        "A5", "Xác định sai số đo tần số kênh A", _TABLE_A5_ROWS, step_results)


def map_table_a6(step_results) -> ReportTable:
    return _map_freq_error_table(
        "A6", "Xác định sai số đo tần số kênh B", _TABLE_A6_ROWS, step_results)


def map_table_a7(step_results) -> ReportTable:
    return _map_freq_error_table(
        "A7", "Xác định sai số đo tần số kênh C", _TABLE_A7_ROWS, step_results)


def map_table_a8(step_results) -> ReportTable:
    """Bảng A8 — Sai số đo chu kỳ, 1 giá trị/dòng."""
    values = _table_values(step_results)
    rows = []
    table_passed = True
    for row_key, freq_set, period_set, display_label in _TABLE_A8_ROWS:
        chunk, values = _consume(values, 1)
        t_meas = chunk[0] if chunk else None
        delta_t = abs(t_meas - period_set) / period_set if t_meas is not None else None

        passed = delta_t is not None and abs(delta_t) <= _FREQ_LIMIT
        if delta_t is not None and not passed:
            table_passed = False

        rows.append(TableRow(
            key=display_label,       # hiển thị "5 Hz (200 ms)" trong bảng
            freq_set=freq_set,
            value_measured=t_meas,
            value_unit="s",
            error=delta_t,
            limit="± 2,4×10⁻⁷",
            passed=passed if delta_t is not None else None,
        ))
    return ReportTable(table_id="A8", name="Xác định sai số đo chu kỳ",
                       rows=rows, passed=table_passed if rows else None,
                       note=_leftover_note("A8", values))


# ---------------------------------------------------------------------------
# Entry point: map toàn bộ kết quả của 1 SessionTest
# ---------------------------------------------------------------------------

TABLE_MAPPERS = {
    "A1": map_table_a1,
    "A2": map_table_a2,
    "A3": map_table_a3,
    "A4": map_table_a4,
    "A5": map_table_a5,
    "A6": map_table_a6,
    "A7": map_table_a7,
    "A8": map_table_a8,
}

# Danh sách row_key hợp lệ cho từng bảng — dùng để dựng dropdown chọn bảng
# đích cho action report_val trong Scenario Builder (gui/scenario_grid.py).
TABLE_ROW_KEYS: dict[str, list[str]] = {
    "A1": [r[0] for r in _TABLE_A1_ROWS],
    "A2": [r[0] for r in _TABLE_A2_ROWS],
    "A3": [r[0] for r in _TABLE_A3_ROWS],
    "A4": [r[0] for r in _TABLE_A4_ROWS],
    "A5": [r[0] for r in _TABLE_A5_ROWS],
    "A6": [r[0] for r in _TABLE_A6_ROWS],
    "A7": [r[0] for r in _TABLE_A7_ROWS],
    "A8": [r[0] for r in _TABLE_A8_ROWS],
}


def map_results(table_id: str, step_results: list) -> Optional[ReportTable]:
    """
    Chuyển danh sách StepResult của một bài test sang ReportTable.

    table_id : "A1" … "A8"
    step_results : list[StepResult] (từ ScenarioRunner.run())
    """
    mapper = TABLE_MAPPERS.get(table_id)
    if mapper is None:
        log.warning("ResultMapper: không có mapper cho bảng %s", table_id)
        return None
    try:
        return mapper(step_results)
    except Exception as exc:  # noqa: BLE001
        log.exception("ResultMapper: lỗi map bảng %s: %s", table_id, exc)
        return None
