"""
unit_test/test_cnt90_real.py
============================
Test kết nối thực tế với Pendulum CNT-90.

Địa chỉ lấy từ --addr-file (key "CNT90"). Nếu không có --real hoặc không
có địa chỉ CNT90 trong file thì tự động SKIP.

Các test dùng raw pyvisa (không qua driver) để tránh *IDN? tự động — vì
CNT-90 trên một số hệ thống gây NI-VISA crash khi bị open_resource ngay
sau khi bus đang ở trạng thái xấu. Nếu open_resource vẫn crash, đó là
vấn đề phần cứng/driver cần xử lý ngoài phần mềm (xem bên dưới).

Chẩn đoán nếu crash ở open_resource:
  1. Kiểm tra địa chỉ GPIB trên màn hình CNT-90 (System → I/O Interface).
  2. Dùng NI-MAX → chuột phải GPIB adapter → "Reset Interface" → "Scan for
     Instruments" để xác nhận địa chỉ thật.
  3. Cập nhật addresses.json với địa chỉ đúng rồi chạy lại.

Chạy:
    pytest unit_test/test_cnt90_real.py --real --addr-file unit_test/addresses.json -v
"""

from __future__ import annotations

import time

import pytest
import pyvisa

DEFAULT_TIMEOUT_MS = 10_000
FETCH_TIMEOUT_MS   = 8_000


# ---------------------------------------------------------------------------
# Fixture: lấy địa chỉ từ addr-file, mở VISA session thô
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cnt90(use_mock, address_map):
    """Mở raw VISA session tới CNT-90. Bỏ qua nếu mock hoặc thiếu địa chỉ."""
    if use_mock:
        pytest.skip("Yêu cầu phần cứng thật — thêm flag --real")

    addr = address_map.get("CNT90")
    if not addr:
        pytest.skip("Thiếu địa chỉ CNT90 trong --addr-file")

    rm   = pyvisa.ResourceManager()
    inst = rm.open_resource(addr)
    inst.timeout           = DEFAULT_TIMEOUT_MS
    inst.read_termination  = "\n"
    inst.write_termination = "\n"

    yield inst

    try:
        inst.close()
    except Exception:
        pass
    try:
        rm.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Mở kết nối
# ---------------------------------------------------------------------------

def test_cnt90_open(cnt90, address_map):
    """VISA resource mở thành công — không exception."""
    assert cnt90 is not None, f"Không mở được resource tại {address_map.get('CNT90')}"


# ---------------------------------------------------------------------------
# 2. *RST — lệnh IEEE-488.2 cơ bản nhất
# ---------------------------------------------------------------------------

def test_cnt90_reset(cnt90):
    """*RST gửi không lỗi và thiết bị ổn định sau 0.5s."""
    cnt90.write("*RST")
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# 3. Cấu hình kênh 3 — đúng lệnh kịch bản
# ---------------------------------------------------------------------------

def test_cnt90_configure_ch3(cnt90):
    """CONF:FREQ (@3) không lỗi — kênh 3 nhận lệnh cấu hình."""
    cnt90.write("*RST")
    time.sleep(0.3)
    cnt90.write("CONF:FREQ (@3)")


# ---------------------------------------------------------------------------
# 4. Đo tần số (pipeline đầy đủ)
# ---------------------------------------------------------------------------

def test_cnt90_measure_frequency(cnt90):
    """
    Pipeline đầy đủ: *RST → timeout → CONF:FREQ (@3) → INIT → FETC?

    FETC? phải trả về số hữu hạn. Giá trị 0 được chấp nhận (không có tín
    hiệu RF vào) — mục tiêu test là kết nối và pipeline, không phải đo RF.
    """
    cnt90.write("*RST")
    time.sleep(0.3)
    cnt90.write(":SYST:TOUT:TIME 5.0")
    cnt90.write(":SYST:TOUT 1")
    cnt90.write("CONF:FREQ (@3)")
    cnt90.write("INIT")

    cnt90.timeout = FETCH_TIMEOUT_MS
    resp = cnt90.query("FETC?").strip()
    cnt90.timeout = DEFAULT_TIMEOUT_MS

    freq = float(resp)          # ValueError nếu máy trả lỗi thay vì số
    assert freq >= 0,    f"Tần số phải ≥ 0 Hz, nhận được: {resp}"
    assert freq < 200e9, f"Giá trị vô lý (> 200 GHz): {freq:.3e} Hz"


# ---------------------------------------------------------------------------
# 5. Gate time round-trip — kiểm tra WRITE + QUERY cùng hoạt động
# ---------------------------------------------------------------------------

def test_cnt90_gate_time_roundtrip(cnt90):
    """
    Đặt gate time 0.1s → đọc lại → kiểm tra khớp trong ±5%.
    Xác nhận lệnh WRITE và QUERY đều hoạt động.
    """
    cnt90.write("*RST")
    time.sleep(0.3)
    target = 0.1
    cnt90.write(f"SENS:ACQ:APER {target:.9f}")
    resp   = cnt90.query("SENS:ACQ:APER?").strip()
    actual = float(resp)
    assert abs(actual - target) / target < 0.05, (
        f"Gate time đặt {target}s, đọc lại {actual}s — lệch quá 5%"
    )
