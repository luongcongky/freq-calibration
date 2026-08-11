"""
core/generic_report_context.py
================================
Context (phần dut/meta, KHÔNG thuộc bảng nào) DÙNG CHUNG cho mọi biểu mẫu
MỚI được đăng ký qua core/table_import.py (khách/quản trị viên tự gắn tag
Jinja trực tiếp trong Word, không qua cơ chế quét/tự động chèn tag) — gom
lại phần logic gần giống hệt nhau đang lặp lại 4 lần trong
core/report_render.py (build_bienban_context_cnt90xl/build_gcnkd_context_cnt90xl/
build_bienban_context_nrp2/build_gcnkd_context_nrp2) thành 1 hàm duy nhất,
tham số hoá bằng 1 file meta.json nhỏ mỗi mẫu thay vì code Python riêng.

Ngoài `dut.*`/`meta.*` (giữ để không phá vỡ gì), còn trả thêm 1 namespace
phẳng `header.*` — đúng tên field mà quản trị viên gõ tay trong Word (vd
`{{ header.name }}`, `{{ header.manager }}`) theo cheat-sheet ở
gui/template_manager_dialog.py.

docxtpl (Jinja2 mặc định, không bật StrictUndefined) hiển thị field không
có trong context thành chuỗi rỗng chứ không lỗi — nên hàm này cứ tính SẴN
union mọi field 4 hàm cũ từng có; file mẫu nào không tham chiếu tới field
nào thì field đó chỉ đơn giản không hiện, không sao.

Không phụ thuộc Qt/docx → test độc lập.
"""

from __future__ import annotations

from core.session import CalibrationSession


def build_meta_context(session: CalibrationSession, meta_json: dict) -> dict:
    meta = session.meta
    dut = meta.dut
    kind = meta_json.get("kind", "kiem_dinh")

    if meta.date:
        d = meta.date
        date_line = f"{d.day:02d} tháng {d.month:02d} năm {d.year}"
        loc = meta.location or "Thành phố Hồ Chí Minh"
        sign_date_line = f"{loc}, ngày {d.day:02d} tháng {d.month:02d} năm {d.year}"
    else:
        date_line = ""
        sign_date_line = ""

    dut_models = meta_json.get("dut_models") or []

    ctx = {
        "dut": {
            "model": dut.model or (dut_models[0] if dut_models else ""),
            "serial": dut.serial,
            "manufacturer": dut.manufacturer or meta_json.get("dut_manufacturer_default", ""),
            "owner": dut.owner,
            "measurement_range": dut.measurement_range or meta_json.get("measurement_range", ""),
        },
        "meta": {
            "inspection_equipment": meta.inspection_equipment,
            "temperature": meta.temperature,
            "humidity": meta.humidity,
            "reviewer": meta.reviewer,
            "operator": meta.operator,
            "cert_number": meta.cert_number,
            "date_line": date_line,
            "cal_date_line": date_line,
            "sign_date_line": sign_date_line,
            "conclusion": "",
            "valid_until_str": "",
        },
    }

    # "Kết luận" (header.conclusion) áp dụng cho MỌI kind — tự động Đạt/Không
    # đạt tính từ session.all_passed ở Bước 3 (gui/session_manager.py::
    # _ExportTab), không riêng gì kiểm định; mẫu hiệu chuẩn (QTHC 2.515) vẫn
    # cần in kết luận cuối cùng vào dòng "Kết quả (Results):" của GCN (trước
    # đây gate theo kind khiến field này LUÔN RỖNG cho mọi mẫu hiệu chuẩn dù
    # docx có tham chiếu {{ header.conclusion }} hay không).
    ctx["meta"]["conclusion"] = meta.conclusion or ""
    if kind == "kiem_dinh":
        ctx["meta"]["valid_until_str"] = (meta.valid_until_str() + ".*") if meta.valid_until else ""

    ctx["header"] = {
        "name": dut.name,
        "no": dut.model,
        "serial": dut.serial,
        "country": dut.manufacturer,
        "birthday": dut.manufacture_year,
        "company": dut.owner,
        "Characteristics": ctx["dut"]["measurement_range"],
        "conclusion": ctx["meta"]["conclusion"],
        "expire": ctx["meta"]["valid_until_str"],
        "reviewer": meta.reviewer,
        "inspector": meta.operator,
        "manager": meta.manager,
        "temperature": meta.temperature,
        "humidity": meta.humidity,
        "equipment": meta.inspection_equipment,
        "cert_no": meta.cert_number,
        "today": date_line,
        "cal_date": date_line,
        "sign_date": sign_date_line,
    }

    return ctx
