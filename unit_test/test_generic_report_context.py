"""
unit_test/test_generic_report_context.py
============================================
Test core/generic_report_context.py::build_meta_context — context dut/meta
DÙNG CHUNG cho mọi biểu mẫu mới tạo qua luồng quét .docx.
"""

from datetime import date

import jinja2

from core.generic_report_context import build_meta_context
from core.session import CalibrationSession, SessionMeta, DUTInfo


def _session(date_val=None, valid_until=None):
    return CalibrationSession(
        template_id="TEST",
        meta=SessionMeta(
            dut=DUTInfo(model="", serial="SN1", manufacturer="", owner="Cty X"),
            operator="A", reviewer="B", cert_number="C1",
            date=date_val, valid_until=valid_until,
        ),
    )


def test_kiem_dinh_includes_conclusion_and_valid_until():
    meta_json = {"kind": "kiem_dinh", "dut_models": ["MODEL1"], "measurement_range": "0-1 GHz"}
    session = _session(date_val=date(2026, 7, 30), valid_until=date(2027, 7, 30))
    ctx = build_meta_context(session, meta_json)
    assert ctx["meta"]["conclusion"] == "Đạt yêu cầu kỹ thuật đo lường"
    assert ctx["meta"]["valid_until_str"].startswith("30/07/2027")
    assert ctx["dut"]["model"] == "MODEL1"   # fallback từ dut_models vì DUT chưa nhập model
    assert ctx["dut"]["measurement_range"] == "0-1 GHz"


def test_hieu_chuan_blanks_valid_until_but_keeps_conclusion():
    """kind=hieu_chuan (QTHC 2.515) không có "Hiệu lực đến" (khái niệm chỉ
    dùng cho kiểm định) — nhưng "Kết luận" (header.conclusion) vẫn phải có
    cho MỌI kind, vì Bước 3 tự tính Đạt/Không đạt cho mọi phiên (kể cả
    hiệu chuẩn) và GCN QTHC 2.515 cần in vào dòng "Kết quả (Results):" —
    trước đây gate nhầm theo kind khiến field này LUÔN RỖNG cho mẫu hiệu
    chuẩn, GCN xuất ra không có kết luận cuối cùng nào (bug thật đã bị
    khách hàng phát hiện)."""
    meta_json = {"kind": "hieu_chuan", "dut_models": ["MODEL1"]}
    session = _session(date_val=date(2026, 7, 30))
    ctx = build_meta_context(session, meta_json)
    assert ctx["meta"]["conclusion"] == session.meta.conclusion
    assert ctx["meta"]["conclusion"] != ""
    assert ctx["meta"]["valid_until_str"] == ""
    assert ctx["meta"]["date_line"] != ""
    assert ctx["meta"]["cal_date_line"] == ctx["meta"]["date_line"]
    assert ctx["meta"]["sign_date_line"].startswith("Thành phố Hồ Chí Minh")


def test_dut_model_from_session_overrides_default():
    meta_json = {"kind": "kiem_dinh", "dut_models": ["FALLBACK_MODEL"]}
    session = _session()
    session.meta.dut.model = "REAL_MODEL"
    ctx = build_meta_context(session, meta_json)
    assert ctx["dut"]["model"] == "REAL_MODEL"


def test_no_date_yields_blank_date_lines():
    meta_json = {"kind": "kiem_dinh"}
    session = _session(date_val=None)
    ctx = build_meta_context(session, meta_json)
    assert ctx["meta"]["date_line"] == ""
    assert ctx["meta"]["sign_date_line"] == ""


def test_missing_field_in_template_renders_blank_not_error():
    """docxtpl không bật StrictUndefined — field context KHÔNG có (vd 1 mẫu
    hiếm khi tham chiếu) phải render ra rỗng, không lỗi."""
    env = jinja2.Environment()
    tpl = env.from_string("[{{ meta.trường_không_tồn_tại }}]")
    ctx = build_meta_context(_session(), {"kind": "kiem_dinh"})
    assert tpl.render(ctx) == "[]"


def test_header_dict_maps_all_nineteen_fields():
    session = _session(date_val=date(2026, 7, 30), valid_until=date(2027, 7, 30))
    session.meta.dut.name = "Máy đếm tần số"
    session.meta.dut.model = "CNT-90XL"
    session.meta.dut.manufacturer = "Pendulum"
    session.meta.dut.manufacture_year = "2023"
    session.meta.manager = "Lê Văn C"
    session.meta.temperature = "23 °C"
    session.meta.humidity = "55 %"
    session.meta.inspection_equipment = "Máy chuẩn X"
    session.meta.cert_number = "GCN-001"
    meta_json = {"kind": "kiem_dinh", "measurement_range": "0,002 Hz đến 27 GHz"}

    ctx = build_meta_context(session, meta_json)
    header = ctx["header"]

    assert header["name"] == "Máy đếm tần số"
    assert header["no"] == "CNT-90XL"
    assert header["serial"] == "SN1"
    assert header["country"] == "Pendulum"
    assert header["birthday"] == "2023"
    assert header["company"] == "Cty X"
    assert header["Characteristics"] == "0,002 Hz đến 27 GHz"
    assert header["conclusion"] == ctx["meta"]["conclusion"]
    assert header["expire"] == ctx["meta"]["valid_until_str"]
    assert header["reviewer"] == "B"
    assert header["inspector"] == "A"
    assert header["manager"] == "Lê Văn C"
    assert header["temperature"] == "23 °C"
    assert header["humidity"] == "55 %"
    assert header["equipment"] == "Máy chuẩn X"
    assert header["cert_no"] == "GCN-001"
    assert header["today"] == ctx["meta"]["date_line"] and header["today"] != ""
    assert header["cal_date"] == ctx["meta"]["cal_date_line"]
    assert header["sign_date"] == ctx["meta"]["sign_date_line"] and header["sign_date"] != ""


def test_header_characteristics_uses_meta_json_fallback():
    session = _session()
    session.meta.dut.measurement_range = ""
    meta_json = {"kind": "hieu_chuan", "measurement_range": "0-1 GHz"}
    ctx = build_meta_context(session, meta_json)
    assert ctx["header"]["Characteristics"] == "0-1 GHz"
