"""
core/report_templates/qthc_2515_nrp2.py
=========================================
Template hiệu chuẩn theo QTHC 2.515 : 2021 cho máy đo công suất NRP2 (R&S).
Gồm 3 bài test (bảng A1–A3). Chỉ bài A2 có sẵn kịch bản thực tế do khách
hàng cung cấp (`cong_suat.json`) — A1/A3 để trống scenario_path vì khách
hàng chưa gửi kịch bản tương ứng; Bước 2 của app sẽ tự hiện "chưa chọn file"
để người dùng biết cần bổ sung.
"""

from __future__ import annotations

from pathlib import Path

from core.session import SessionTest, ReportTable
from core.result_mapper_nrp2 import map_results_nrp2
from .base import BaseReportTemplate

_SCEN_DIR = Path(__file__).parent.parent.parent / "scenarios" / "nrp2"


class QTHC2515NRP2Template(BaseReportTemplate):
    TEMPLATE_ID = "QTHC_2515_NRP2"
    TEMPLATE_NAME = "QTHC 2.515 : 2021 — Máy đo công suất NRP2 (R&S)"
    DUT_MODELS = ["NRP2"]
    STANDARD = "QTHC 2.515 : 2021"
    MEASUREMENT_RANGE = ("Dải tần làm việc từ DC đến 110 GHz; "
                        "dải đo công suất từ (-67 đến 45) dBm")

    # (table_id, tên bài test, tên file kịch bản trong scenarios/nrp2/ — "" nếu chưa có)
    _TEST_DEFS = [
        ("A1", "Xác định độ chính xác mức công suất tại đầu ra chuẩn", ""),
        ("A2", "Xác định độ chính xác đo mức công suất tuyệt đối (tại 0 dBm)", "cong_suat.json"),
        ("A3", "Xác định độ chính xác đo công suất với NRPC50 calibration kit", ""),
    ]

    def default_tests(self) -> list[SessionTest]:
        tests = []
        for table_id, name, filename in self._TEST_DEFS:
            path = str(_SCEN_DIR / filename) if filename else ""
            tests.append(SessionTest(
                table_id=table_id,
                name=name,
                scenario_path=path,
                enabled=True,
                status="pending",
            ))
        return tests

    def map_test_result(self, test: SessionTest) -> ReportTable:
        return map_results_nrp2(test.table_id, test.step_results)

    def generate_bienban(self, session, output_path):
        from core.report_generator_nrp2 import generate_bienban as _gen
        return _gen(session, output_path)

    def generate_gcnkd(self, session, output_path):
        from core.report_generator_nrp2 import generate_gcnkd as _gen
        return _gen(session, output_path)

    @property
    def scenarios_dir(self) -> Path:
        return _SCEN_DIR
