# Hướng dẫn Driver Thiết bị (Drivers Guide)

Mỗi **model** là một class driver chuyên biệt, dùng chung lớp transport
`VisaInstrument` để tránh lặp boilerplate kết nối. Tất cả hỗ trợ **mock mode**
(chạy offline, không cần phần cứng) phục vụ test và demo.

Tập trung tra cứu tại `DEVICE_REGISTRY` ([__init__.py](file:///c:/DATA/Projects/freq_calibration/drivers/__init__.py)):
`{model_key: {category, cls, vendor}}` với `category` ∈ {`counter`, `power`}.

---

## 1. `base_visa.py` — Lớp transport dùng chung

`VisaInstrument`: quản lý phiên VISA + mock + I/O cấp thấp.

| Nhóm | Thành phần |
| :-- | :-- |
| Kết nối | `connect()`, `disconnect()`, context manager `with`, xác thực `IDN_KEYWORDS` |
| I/O | `_write()`, `_query()` (mock gọi `_mock_response()`), `set_timeout()` |
| Định danh | `identify()`, `get_model()` (bóc model từ `*IDN?`), `get_status()` |
| Chẩn đoán | `get_all_errors()`, `reset()`, `clear_status()`, `wait_for_completion()` |
| Kết quả | dataclass `Reading(value, unit, channel, raw)` |

Driver con khai báo `IDN_KEYWORDS`, `MODEL_NAME` và override `_mock_idn()` /
`_mock_response()` để mô phỏng đúng "giọng" máy thật.

---

## 2. Máy đếm tần số (category = `counter`)

Hành động chuẩn giai đoạn 1: **set_gate_time()** (điều khiển) + **measure_frequency()**
(thu thập) → `Reading` đơn vị Hz.

| File | Model | Ghi chú |
| :-- | :-- | :-- |
| `pendulum_counters.py` | CNT-85, CNT-90, CNT-91 | SCPI (`SENS:ACQ:APER`, `MEAS:FREQ?`). CNT-85 best-effort. |
| `keysight_counters.py` | 53131A, 53132A, 53220A | Universal counter. 531x1A đặt gate qua khối `FREQ:ARM:STOP:TIM`. |
| `keysight_counters.py` | 53150A, 53151A, 53147A | Microwave CW counter; 53147A còn `measure_power()`. |
| `fluke_counters.py` | PM6690 | SCPI ≈ CNT-90. |
| `fluke_counters.py` | PM6680 | Philips đời cũ; có cờ `USE_LEGACY_SYNTAX`, best-effort. |
| `advantest_r5372p.py` | R5372P | **Legacy non-SCPI**, best-effort + `TODO(hardware)`. |

Driver gốc `cnt90xl.py` (Pendulum CNT-90XL, rất giàu tính năng) vẫn còn nhưng dùng
API riêng (`MeasurementResult`, `StatisticsResult`) và **không** nằm trong registry;
dòng CNT-90/90XL được class `CNT90` (API thống nhất) bao phủ.

---

## 3. Máy đo công suất (category = `power`)

Hành động chuẩn: **set_frequency()** (chọn cal factor) + **measure_power()** →
`Reading` đơn vị dBm; kèm tiện ích **zero()**.

| File | Model | Ghi chú |
| :-- | :-- | :-- |
| `keysight_power.py` | E4410A, N1911A, N1913A, N1914A | SCPI (`SENS:FREQ`, `FETC?`, `CAL:ZERO:AUTO ONCE`). N1914A 2 kênh. |
| `boonton_4231a.py` | 4231A | **Legacy non-SCPI**, best-effort + `TODO(hardware)`. |

Driver gốc `smw200a.py` (R&S SMW200A — máy phát tín hiệu) vẫn còn để dùng làm
chuẩn phát, không thuộc registry kiểm định.

---

## 4. Máy đời cũ (legacy, best-effort)

Advantest R5372P, Boonton 4231A và một phần PM6680 dùng tập lệnh GPIB riêng (không
phải SCPI) và thường **không có `*IDN?`**. Trong các driver này:

- Các hằng `CMD_*` là **PLACEHOLDER**, đánh dấu `TODO(hardware)` — **phải đối chiếu
  manual** và chỉnh trước khi chạy máy thật.
- `identify()` có fallback (không raise khi máy không trả `*IDN?`).
- Với các máy này nên dùng **Wizard cắm-từng-máy** trong Device Manager để gán địa
  chỉ thay vì dựa vào auto-`*IDN?`.

---

## 5. Điểm thiết kế quan trọng

- **Tự nới timeout** theo gate time/averaging để tránh `VisaIOError` khi đo lâu.
- **Validation tại driver**: kiểm tra đầu vào (dải tần, gate time…) và `raise` rõ
  ràng thay vì đợi máy báo lỗi SCPI.
- **Sẵn sàng remote**: đổi địa chỉ `GPIB0::n::INSTR` → `TCPIP0::<ip>::gpib0,n::INSTR`
  để dùng VISA-over-IP qua Tailscale/VPN mà không đổi logic.
- **Mock-first**: mọi driver chạy được ở mock → toàn bộ test pytest chạy offline.

---

## 6. Mẫu dùng nhanh

```python
from drivers import DEVICE_REGISTRY

cls = DEVICE_REGISTRY["CNT91"]["cls"]
with cls("GPIB0::3::INSTR") as dev:          # bỏ mock=True khi có phần cứng
    print(dev.get_model())                   # nhận diện
    dev.set_gate_time(0.1)                    # điều khiển
    print(dev.measure_frequency())           # thu thập → Reading(Hz)
```
