"""
unit_test/test_devices.py
=========================
Test giai đoạn 1 cho TẤT CẢ thiết bị trong DEVICE_REGISTRY:

  1. Kết nối + nhận diện model   (test_connect_and_identify, test_get_model)
  2. MỘT lệnh điều khiển          (test_control)
  3. MỘT lệnh thu thập số liệu    (test_acquire)
  + ảnh chụp trạng thái           (test_get_status)

Mặc định chạy MOCK (offline). Với phần cứng thật:
    pytest unit_test --real --addr-file unit_test/addresses.json

Quy ước hành động theo nhóm thiết bị (category):
  - counter : control = set_gate_time(0.1s) ; acquire = measure_frequency() -> Hz
  - power   : control = set_frequency(50MHz) ; acquire = measure_power()    -> dBm
"""

import math

import pytest

from drivers import DEVICE_REGISTRY, Reading

ALL_MODELS = list(DEVICE_REGISTRY.keys())
COUNTERS = [k for k, v in DEVICE_REGISTRY.items() if v["category"] == "counter"]
POWER_METERS = [k for k, v in DEVICE_REGISTRY.items() if v["category"] == "power"]
GENERATORS = [k for k, v in DEVICE_REGISTRY.items() if v["category"] == "generator"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(model_key, use_mock, address_map):
    """Tạo & kết nối driver cho model_key (mock hoặc real)."""
    entry = DEVICE_REGISTRY[model_key]
    cls = entry["cls"]
    if use_mock:
        return cls(f"MOCK::{model_key}", mock=True)
    addr = address_map.get(model_key)
    if not addr:
        pytest.skip(f"--real nhưng thiếu địa chỉ VISA cho '{model_key}' (xem --addr-file)")
    return cls(addr)


def _do_control(model_key, dev):
    """Thực hiện 1 lệnh điều khiển phù hợp nhóm thiết bị."""
    category = DEVICE_REGISTRY[model_key]["category"]
    if category == "counter":
        dev.set_gate_time(0.1)
    elif category == "power":
        dev.set_frequency(50e6)
    elif category == "generator":
        dev.set_frequency(1e9)
    else:
        pytest.fail(f"Category không hỗ trợ: {category}")


def _do_acquire(model_key, dev) -> Reading:
    """Thực hiện 1 lệnh thu thập số liệu phù hợp nhóm thiết bị."""
    category = DEVICE_REGISTRY[model_key]["category"]
    if category == "counter":
        return dev.measure_frequency()
    if category == "power":
        return dev.measure_power()
    if category == "generator":
        return dev.measure_frequency()
    pytest.fail(f"Category không hỗ trợ: {category}")


@pytest.fixture
def device(request, use_mock, address_map):
    """Fixture indirect: nhận model_key qua param, trả (model_key, driver)."""
    model_key = request.param
    dev = _make_device(model_key, use_mock, address_map)
    try:
        yield model_key, dev
    finally:
        dev.disconnect()


# ---------------------------------------------------------------------------
# 1. Kết nối + nhận diện
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device", ALL_MODELS, indirect=True)
def test_connect_and_identify(device, use_mock):
    """*IDN? trả chuỗi không rỗng; ở mock phải chứa từ khóa nhận diện model."""
    model_key, dev = device
    idn = dev.identify()
    assert isinstance(idn, str) and idn.strip(), f"{model_key}: *IDN? rỗng"

    keywords = DEVICE_REGISTRY[model_key]["cls"].IDN_KEYWORDS
    if use_mock and keywords:
        assert any(k in idn for k in keywords), (
            f"{model_key}: *IDN? '{idn}' không chứa từ khóa {keywords}"
        )


@pytest.mark.parametrize("device", ALL_MODELS, indirect=True)
def test_get_model(device):
    """get_model() bóc được tên model 'sạch' từ *IDN?."""
    model_key, dev = device
    model = dev.get_model()
    assert isinstance(model, str) and model.strip(), f"{model_key}: get_model() rỗng"


@pytest.mark.parametrize("device", ALL_MODELS, indirect=True)
def test_get_status(device):
    """get_status() trả dict có thông tin cơ bản."""
    model_key, dev = device
    st = dev.get_status()
    assert isinstance(st, dict)
    assert st.get("model_name"), f"{model_key}: thiếu model_name trong status"
    assert "idn" in st, f"{model_key}: thiếu idn trong status"


# ---------------------------------------------------------------------------
# 2. Một lệnh điều khiển
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device", ALL_MODELS, indirect=True)
def test_control(device):
    """Gửi 1 lệnh điều khiển (set gate time / set frequency) không lỗi."""
    model_key, dev = device
    _do_control(model_key, dev)  # raise nếu thất bại -> test fail


# ---------------------------------------------------------------------------
# 3. Một lệnh thu thập số liệu
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device", ALL_MODELS, indirect=True)
def test_acquire(device):
    """Thu thập 1 số liệu, kiểm tra kiểu/đơn vị/giá trị hợp lệ."""
    model_key, dev = device
    # Điều khiển trước rồi mới đo, mô phỏng đúng trình tự thực tế.
    _do_control(model_key, dev)
    reading = _do_acquire(model_key, dev)

    assert isinstance(reading, Reading), f"{model_key}: kết quả không phải Reading"
    assert math.isfinite(reading.value), f"{model_key}: giá trị không hữu hạn"

    category = DEVICE_REGISTRY[model_key]["category"]
    if category == "counter":
        assert reading.unit == "Hz", f"{model_key}: đơn vị phải là Hz"
        assert reading.value > 0, f"{model_key}: tần số phải > 0"
    elif category == "power":
        assert reading.unit == "dBm", f"{model_key}: đơn vị phải là dBm"
    elif category == "generator":
        assert reading.unit == "Hz", f"{model_key}: đơn vị phải là Hz"
        assert reading.value > 0, f"{model_key}: tần số phải > 0"


# ---------------------------------------------------------------------------
# Sanity: registry phủ đủ cả 3 nhóm
# ---------------------------------------------------------------------------

def test_registry_coverage():
    assert COUNTERS, "Registry phải có ít nhất 1 máy đếm tần số"
    assert POWER_METERS, "Registry phải có ít nhất 1 máy đo công suất"
    assert GENERATORS, "Registry phải có ít nhất 1 máy phát tín hiệu"
    assert len(ALL_MODELS) == len(set(ALL_MODELS)), "Có model_key trùng lặp"
