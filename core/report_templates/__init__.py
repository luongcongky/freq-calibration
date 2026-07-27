"""
core/report_templates/__init__.py
==================================
Registry các template báo cáo kiểm định.

Mỗi template ứng với một loại thiết bị + tiêu chuẩn cụ thể.
Để thêm template mới: tạo file .py trong thư mục này, kế thừa BaseReportTemplate,
sau đó đăng ký vào REGISTRY bên dưới.
"""

from __future__ import annotations

from .base import BaseReportTemplate
from .qtkd_2461_cnt90xl import QTKD2461CNT90XLTemplate
from .qthc_2515_nrp2 import QTHC2515NRP2Template

REGISTRY: dict[str, type[BaseReportTemplate]] = {
    "QTKD_2461_CNT90XL": QTKD2461CNT90XLTemplate,
    "QTHC_2515_NRP2": QTHC2515NRP2Template,
}


def get_template(template_id: str) -> BaseReportTemplate:
    cls = REGISTRY.get(template_id)
    if cls is None:
        raise KeyError(f"Template không tồn tại: '{template_id}'. "
                       f"Có sẵn: {list(REGISTRY)}")
    return cls()


def list_templates() -> list[tuple[str, str]]:
    """Trả [(id, display_name), ...] để hiển thị trong combobox."""
    return [(tid, cls().TEMPLATE_NAME) for tid, cls in REGISTRY.items()]
