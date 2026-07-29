"""
core/result_mapper_nrp2.py
===========================
Chuyển StepResult (từ ScenarioRunner) sang ReportTable cho template
QTHC 2.515:2021 (máy đo công suất NRP2) — TÁCH RIÊNG khỏi
core/result_mapper.py vì cả 2 template đều dùng mã bảng "A1"/"A2"/"A3" và
không được dùng chung 1 dict TABLE_MAPPERS (sẽ áp nhầm hàm map của
CNT-90XL cho dữ liệu NRP2).

Kịch bản đẩy giá trị vào báo cáo bằng action "report_val" (chỉ 1 tham số
value — không cần khai bảng đích, vì 1 lần chạy kịch bản luôn ứng với đúng
1 bài test/1 bảng). ResultMapper lấy TUẦN TỰ các StepResult report_val
(đúng thứ tự thực thi, kể cả trong Loop) rồi tách theo số giá trị/dòng đã
định nghĩa sẵn cho bảng đó để đổ vào từng TableRow.

QTHC 2.515:2021 là văn bản HIỆU CHUẨN (báo cáo giá trị + số hiệu chỉnh +
độ không đảm bảo đo), không phải KIỂM ĐỊNH (đạt/không đạt) như QTKĐ 2.461 —
nên mọi TableRow ở đây luôn có passed=None, limit="" (không có ngưỡng); field
`error` được dùng lại với ý nghĩa "Số hiệu chỉnh" (giá trị chuẩn − giá trị
đo trung bình), không phải sai số tương đối.

Không phụ thuộc Qt/docx → test được độc lập.
"""

from __future__ import annotations

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
# Helper lấy giá trị report_val tuần tự (giống result_mapper.py, thuần generic)
# ---------------------------------------------------------------------------

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


# TableRow.limit không mang ý nghĩa ngưỡng đạt/không đạt ở QTHC 2.515 (không
# có khái niệm này) — để trống; giữ field lại vì report_generator_nrp2.py/
# report_preview_nrp2.py dùng chung cấu trúc TableRow với template CNT-90XL.

# ---------------------------------------------------------------------------
# Mapping từng bảng
# ---------------------------------------------------------------------------

def map_table_a1(step_results) -> ReportTable:
    """Mục 5.3.1: 1 điểm, đo _A1_N_LAN (10) lần lặp lại — 1 dòng duy nhất."""
    from core.report_generator_nrp2 import _A1_N_LAN
    values = _table_values(step_results)
    rows = []
    for row_key, freq_hz, power_set_w in _TABLE_A1_ROWS:
        raws, values = _consume(values, _A1_N_LAN)
        p_avg = sum(raws) / len(raws) if raws else None
        correction = (power_set_w - p_avg) if p_avg is not None else None
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="W",
            error=correction, limit="", passed=None,
            raw_readings=raws,
        ))
    return ReportTable(table_id="A1",
                       name="Xác định độ chính xác mức công suất tại đầu ra chuẩn",
                       rows=rows, passed=None, note=_leftover_note("A1", values))


def map_table_a2(step_results) -> ReportTable:
    """Mục 5.3.2: đo 5 lần lặp lại mỗi điểm tần số — Biên Bản ghi từng lần
    + TB, GCN chỉ ghi TB + số hiệu chỉnh (xem report_generator_nrp2.py)."""
    values = _table_values(step_results)
    rows = []
    for row_key, freq_hz in _TABLE_A2_ROWS:
        raws, values = _consume(values, 5)
        p_avg = sum(raws) / len(raws) if raws else None
        correction = (_A2_POWER_SET_DBM - p_avg) if p_avg is not None else None
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="dBm",
            error=correction, limit="", passed=None,
            raw_readings=raws,
        ))
    return ReportTable(table_id="A2",
                       name="Xác định độ chính xác đo mức công suất tuyệt đối (tại 0 dBm)",
                       rows=rows, passed=None, note=_leftover_note("A2", values))


def map_table_a3(step_results) -> ReportTable:
    """Mục 5.3.3: đo 5 lần lặp lại mỗi điểm (tần số, công suất) — cùng cách
    ghi như A2."""
    values = _table_values(step_results)
    rows = []
    for row_key, freq_hz, power_set_dbm in _TABLE_A3_ROWS:
        raws, values = _consume(values, 5)
        p_avg = sum(raws) / len(raws) if raws else None
        correction = (power_set_dbm - p_avg) if p_avg is not None else None
        rows.append(TableRow(
            key=row_key, freq_set=freq_hz, value_measured=p_avg, value_unit="dBm",
            error=correction, limit="", passed=None,
            raw_readings=raws,
        ))
    return ReportTable(table_id="A3",
                       name="Xác định độ chính xác đo công suất với bộ hiệu chuẩn "
                            "công suất NRPC50 calibration kit",
                       rows=rows, passed=None, note=_leftover_note("A3", values))


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
    return mapper(step_results)
