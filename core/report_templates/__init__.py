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
from .generic import GenericReportTemplate, load_generic_meta, discover_generic_template_ids

REGISTRY: dict[str, type[BaseReportTemplate]] = {}


def get_template(template_id: str) -> BaseReportTemplate:
    cls = REGISTRY.get(template_id)
    if cls is not None:
        return cls()
    if load_generic_meta(template_id) is not None:
        return GenericReportTemplate(template_id)
    raise KeyError(f"Template không tồn tại: '{template_id}'. "
                   f"Có sẵn: {list(REGISTRY) + discover_generic_template_ids()}")


def list_templates() -> list[tuple[str, str]]:
    """Trả [(id, display_name), ...] để hiển thị trong combobox — gồm cả
    template viết tay (REGISTRY) lẫn template data-driven tạo qua luồng
    quét .docx (templates/<id>/meta.json)."""
    result = [(tid, cls().TEMPLATE_NAME) for tid, cls in REGISTRY.items()]
    for tid in discover_generic_template_ids():
        if tid not in REGISTRY:
            meta = load_generic_meta(tid)
            result.append((tid, meta.get("template_name", tid) if meta else tid))
    return result
