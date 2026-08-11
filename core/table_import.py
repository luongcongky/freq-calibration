"""
core/table_import.py
======================
Lớp điều phối (orchestration) cho "Quản lý mẫu báo cáo" (gui/
template_manager_dialog.py) — KHÔNG còn đường "tạo mẫu rỗng" (mọi mẫu mới
đều bắt đầu từ SAO CHÉP 1 mẫu đã có, xem copy_template()). Việc của module
này: sao chép/sửa/xoá file — copy nguyên vẹn .docx, đọc/ghi meta.json, ghi
descriptor JSON (core/table_wizard_io.py::write_descriptor_json), chuyển cả
thư mục mẫu vào Thùng rác khi xoá (delete_template()).

GUI chỉ thu thập input qua màn hình review rồi gọi thẳng vào đây — không có
logic nghiệp vụ nào nằm trong lớp Qt.

Không phụ thuộc Qt → test độc lập.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from core import table_wizard_io as wio
from core.table_descriptor import TableDescriptor, load_table_descriptors


def copy_template(source_id: str, new_id: str, new_name: str) -> Path:
    """Sao chép NGUYÊN VẸN 1 mẫu đã có (meta.json + tables/*.json + 2 file
    .docx) sang template_id MỚI — nguồn duy nhất để tạo 1 mẫu mới (không
    còn luồng "tạo mẫu rỗng" từ file khách tự cung cấp). Chỉ đổi
    template_id + template_name trong meta.json, giữ nguyên mọi nội dung
    khác (model DUT, tiêu chuẩn, dải đo, toàn bộ bảng, toàn bộ tag trong
    docx) — người dùng tự sửa lại sau qua trình sửa mẫu."""
    from core.report_templates.generic import TEMPLATES_DIR
    src_dir = TEMPLATES_DIR / source_id
    dst_dir = TEMPLATES_DIR / new_id
    if not src_dir.exists():
        raise ValueError(f"Mẫu nguồn '{source_id}' không tồn tại.")
    if dst_dir.exists():
        raise ValueError(f"Mẫu '{new_id}' đã tồn tại — hãy chọn mã khác.")

    shutil.copytree(src_dir, dst_dir)

    meta_path = dst_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["template_id"] = new_id
    meta["template_name"] = new_name or meta.get("template_name", new_id)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return dst_dir


def delete_template(template_id: str) -> None:
    """Xoá 1 mẫu báo cáo — chuyển NGUYÊN CẢ THƯ MỤC vào Thùng rác (Recycle
    Bin) qua send2trash, KHÔNG xoá vĩnh viễn ngay — lỡ tay xoá nhầm vẫn khôi
    phục được từ Thùng rác Windows, không như shutil.rmtree (mất luôn)."""
    from send2trash import send2trash
    from core.report_templates.generic import TEMPLATES_DIR
    tpl_dir = TEMPLATES_DIR / template_id
    if not tpl_dir.exists():
        raise ValueError(f"Mẫu '{template_id}' không tồn tại.")
    send2trash(str(tpl_dir))


def update_meta(template_id: str, meta_fields: dict) -> Path:
    """Ghi đè các field có thể sửa trong meta.json của 1 mẫu ĐÃ CÓ — KHÔNG
    đổi template_id (đổi mã mẫu nghĩa là tạo mẫu khác, dùng copy_template)."""
    from core.report_templates.generic import TEMPLATES_DIR
    meta_path = TEMPLATES_DIR / template_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in ("template_name", "kind", "dut_models", "standard",
                "measurement_range", "dut_manufacturer_default"):
        if key in meta_fields:
            meta[key] = meta_fields[key]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def replace_docx(template_id: str, which: str, new_path) -> Path:
    """Thay bienban.docx hoặc gcnkd.docx của 1 mẫu ĐÃ CÓ bằng file MỚI đã
    gắn tag sẵn (copy nguyên vẹn, không mở/sửa gì) — which: 'bienban' |
    'gcnkd'."""
    from core.report_templates.generic import TEMPLATES_DIR
    dest = TEMPLATES_DIR / template_id / f"{which}.docx"
    shutil.copy(str(new_path), str(dest))
    return dest


def copy_table(tables_dir, source_id: str, new_id: str, new_name: str = "") -> Path:
    """Sao chép 1 bảng ĐÃ CÓ trong CÙNG 1 mẫu thành bảng MỚI (table_id khác)
    — copy nguyên rows/columns/merge/pass_rule/value_format (kể cả bảng
    NÂNG CAO: measured_count/value_format_seq/uncertainty_index đi theo).
    Đặt lại scenario_file="" (ánh xạ kịch bản gắn theo table_id cũ, bảng
    mới cần gán lại kịch bản riêng) và order = lớn nhất hiện có + 1 (thêm
    vào cuối danh sách hiển thị)."""
    tables_dir = Path(tables_dir)
    descriptors = load_table_descriptors(tables_dir)
    source = next((d for d in descriptors if d.table_id == source_id), None)
    if source is None:
        raise ValueError(f"Bảng nguồn '{source_id}' không tồn tại.")
    err = wio.validate_table_id_available(tables_dir, new_id)
    if err:
        raise ValueError(err)

    new_descriptor = copy.deepcopy(source)
    new_descriptor.table_id = new_id
    new_descriptor.name = new_name.strip() if new_name.strip() else f"{source.name} (bản sao)"
    new_descriptor.scenario_file = ""
    new_descriptor.order = max((d.order for d in descriptors), default=0) + 1
    return wio.write_descriptor_json(new_descriptor, tables_dir)


def apply_table_to_existing(tables_dir, descriptor: TableDescriptor) -> Path:
    """Ghi 1 bảng (mới HOẶC sửa đè bảng đã có, tuỳ table_id trùng hay
    không) vào biểu mẫu ĐÃ CÓ — CHỈ ghi file JSON descriptor. KHÔNG đụng
    bienban.docx/gcnkd.docx sống — quản trị viên tự gõ/sửa tag tương ứng
    trong 2 file đó bằng Word, ngoài luồng app."""
    return wio.write_descriptor_json(descriptor, tables_dir)
