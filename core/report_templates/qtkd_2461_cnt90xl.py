"""
core/report_templates/qtkd_2461_cnt90xl.py
===========================================
Template kiểm định theo QTKĐ 2.461 : 2018 cho máy đếm tần số CNT-90XL (Pendulum).
Gồm 8 bài test (bảng A1–A8), mỗi bài tương ứng một file scenario JSON.
"""

from __future__ import annotations

from pathlib import Path

from core.session import SessionTest, ReportTable
from core.result_mapper import map_results
from .base import BaseReportTemplate

# Thư mục chứa 8 file scenario của template này
_SCEN_DIR = Path(__file__).parent.parent.parent / "scenarios" / "cnt90xl"


class QTKD2461CNT90XLTemplate(BaseReportTemplate):
    TEMPLATE_ID = "QTKD_2461_CNT90XL"
    TEMPLATE_NAME = "QTKĐ 2.461 : 2018 — Máy đếm tần số CNT-90XL (Pendulum)"
    DUT_MODELS = ["CNT-90XL", "CNT-90"]
    STANDARD = "QTKĐ 2.461 : 2018"
    MEASUREMENT_RANGE = "0,002 Hz đến 27 GHz"

    # Định nghĩa 8 bài test theo đúng thứ tự trong mẫu biên bản
    _TEST_DEFS = [
        ("A1", "Xác định sai số tần số bộ dao động thạch anh",  "01_oscillator_error.json"),
        ("A2", "Xác định độ nhạy đầu vào kênh A",               "02_sensitivity_chA.json"),
        ("A3", "Xác định độ nhạy đầu vào kênh B",               "03_sensitivity_chB.json"),
        ("A4", "Xác định độ nhạy đầu vào kênh C",               "04_sensitivity_chC.json"),
        ("A5", "Xác định sai số đo tần số kênh A",              "05_freq_error_chA.json"),
        ("A6", "Xác định sai số đo tần số kênh B",              "06_freq_error_chB.json"),
        ("A7", "Xác định sai số đo tần số kênh C",              "07_freq_error_chC.json"),
        ("A8", "Xác định sai số đo chu kỳ",                     "08_period_error.json"),
    ]

    def default_tests(self) -> list[SessionTest]:
        tests = []
        for table_id, name, filename in self._TEST_DEFS:
            path = _SCEN_DIR / filename
            tests.append(SessionTest(
                table_id=table_id,
                name=name,
                scenario_path=str(path),
                enabled=True,
                status="pending",
            ))
        return tests

    def map_test_result(self, test: SessionTest) -> ReportTable:
        return map_results(test.table_id, test.step_results)

    @property
    def scenarios_dir(self) -> Path:
        return _SCEN_DIR
