"""
core/report_templates/generic.py
==================================
Template báo cáo HOÀN TOÀN DATA-DRIVEN — phục vụ các biểu mẫu do quản trị
viên tự gắn tag Jinja tay trong Word rồi đăng ký qua core/table_import.py +
gui/template_manager_dialog.py, KHÔNG cần viết class Python riêng như
QTKD2461CNT90XLTemplate/QTHC2515NRP2Template.

Mọi thứ (danh sách bài test, cách map kết quả, cách render Biên Bản/GCN)
đều đọc từ đĩa lúc khởi tạo: templates/<template_id>/meta.json +
templates/<template_id>/tables/*.json + bienban.docx/gcnkd.docx.

GCN của mọi biểu mẫu tạo qua luồng này luôn theo kiểu "giống Biên Bản" (mỗi
bảng có tag riêng trong gcnkd.docx, như NRP2) — KHÔNG dùng kiểu "bảng tổng
hợp 1 dòng/bài" (chỉ CNT90XL viết tay đang có, cần dữ liệu tổng hợp không
có sẵn cho 1 mẫu hoàn toàn mới).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.session import CalibrationSession, SessionTest, ReportTable
from core.table_descriptor import load_table_descriptors
from core.generic_report_context import build_meta_context
from core import table_engine
from core.paths import TEMPLATES_DIR, SCENARIOS_DIR as _SCENARIOS_ROOT
from .base import BaseReportTemplate


def load_generic_meta(template_id: str) -> Optional[dict]:
    path = TEMPLATES_DIR / template_id / "meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def discover_generic_template_ids() -> list:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(
        p.parent.name for p in TEMPLATES_DIR.glob("*/meta.json")
    )


def template_summary(template_id: str) -> Optional[dict]:
    """Thông tin gọn để hiển thị danh sách mẫu ("Quản lý mẫu báo cáo") —
    chỉ đọc meta.json + đếm file bảng, không cần dựng cả GenericReportTemplate."""
    meta = load_generic_meta(template_id)
    if meta is None:
        return None
    tables_dir = TEMPLATES_DIR / template_id / "tables"
    n_tables = len(list(tables_dir.glob("*.json"))) if tables_dir.exists() else 0
    return {
        "template_id": template_id,
        "template_name": meta.get("template_name", template_id),
        "kind": meta.get("kind", "kiem_dinh"),
        "dut_models": meta.get("dut_models", []),
        "n_tables": n_tables,
    }


class GenericReportTemplate(BaseReportTemplate):
    def __init__(self, template_id: str):
        meta = load_generic_meta(template_id)
        if meta is None:
            raise KeyError(f"Không tìm thấy templates/{template_id}/meta.json")

        self.TEMPLATE_ID = template_id
        self.TEMPLATE_NAME = meta.get("template_name", template_id)
        self.DUT_MODELS = meta.get("dut_models", [])
        self.STANDARD = meta.get("standard", "")
        self.MEASUREMENT_RANGE = meta.get("measurement_range", "")

        self._meta_json = meta
        base = TEMPLATES_DIR / template_id
        self._tables_dir = base / "tables"
        self._bienban_template = base / "bienban.docx"
        self._gcnkd_template = base / "gcnkd.docx"
        self._scen_dir = _SCENARIOS_ROOT / template_id.lower()
        self._descriptors = load_table_descriptors(self._tables_dir)

    def default_tests(self) -> list:
        tests = []
        for d in self._descriptors:
            path = self._scen_dir / d.scenario_file if d.scenario_file else ""
            tests.append(SessionTest(
                table_id=d.table_id, name=d.name, scenario_path=str(path),
                enabled=True, status="pending",
            ))
        return tests

    def map_test_result(self, test: SessionTest) -> Optional[ReportTable]:
        descriptor = self.descriptor_for(test.table_id)
        if descriptor is None:
            return None
        return table_engine.map_table(descriptor, test.step_results)

    def descriptor_for(self, table_id: str):
        return next((d for d in self._descriptors if d.table_id == table_id), None)

    def generate_bienban(self, session: CalibrationSession, output_path) -> Path:
        return table_engine.render_with_table_contexts(
            session, self._descriptors, self._bienban_template, output_path,
            lambda s: build_meta_context(s, self._meta_json),
        )

    def generate_gcnkd(self, session: CalibrationSession, output_path) -> Path:
        return table_engine.render_with_table_contexts(
            session, self._descriptors, self._gcnkd_template, output_path,
            lambda s: build_meta_context(s, self._meta_json),
        )

    @property
    def tables_dir(self) -> Path:
        return self._tables_dir

    @property
    def bienban_docx_path(self) -> Path:
        return self._bienban_template

    @property
    def gcnkd_docx_path(self) -> Path:
        return self._gcnkd_template

    @property
    def scenarios_dir(self) -> Path:
        return self._scen_dir
