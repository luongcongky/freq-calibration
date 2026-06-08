# Tổng quan Core Logic (Core Guide)

Các module lõi (không phụ thuộc Qt → kiểm thử được bằng pytest) cho hệ thống
kịch bản **grid step-by-step, đa thiết bị**.

> Luồng file `.txt` cũ (`sequence.py`, `measurement.py`, `report.py`,
> `simulation.py`) đã được **loại bỏ**. Toàn bộ kịch bản nay dùng mô hình
> `Scenario` + `ScenarioRunner`.

---

## 1. `core/scenario.py` — Mô hình kịch bản

Định nghĩa kịch bản grid và metadata cho GUI dựng form.

- **`ScenarioStep`**: một bước = `action` + danh sách `devices` (model_key trong
  `DEVICE_REGISTRY`) + `params` + `note` + `enabled`. Một bước có thể nhắm **nhiều
  thiết bị** (chạy cùng hành động).
- **`Scenario`**: danh sách bước + tên/mô tả; `add_step()`, `move()`, và
  **serialize JSON** (`save_json()` / `load_json()`).
- **`ACTION_SPECS`**: danh mục hành động (metadata: nhãn, nhóm thiết bị áp dụng,
  tham số). Hành động hiện có: `identify`, `status`, `set_gate_time`,
  `measure_frequency` (counter); `set_frequency`, `zero`, `measure_power` (power);
  `wait` (không cần thiết bị).
- **`actions_for_devices()`**: lọc hành động hợp lệ cho tập thiết bị đang chọn
  (giao của các nhóm) — dùng để combo action trong GUI tự cập nhật.
- **`validate_scenario()`**: bắt lỗi logic trước khi chạy (action sai nhóm thiết
  bị, thiếu tham số, thiếu thiết bị, model không có trong registry).

---

## 2. `core/scenario_runner.py` — Bộ thực thi

Mở thiết bị, chạy kịch bản, phát kết quả từng bước.

- **`ScenarioRunner(mock, address_map, on_result, stop_flag)`**: mở (connect) một
  lần mỗi thiết bị xuất hiện trong kịch bản, duyệt từng bước đang bật, chạy hành
  động cho từng thiết bị, đóng toàn bộ khi xong (kể cả khi lỗi). `mock=True` chạy
  offline; `mock=False` cần `address_map` (model→địa chỉ VISA).
- **`StepResult`**: kết quả mỗi (bước, thiết bị) — `value/unit` cho phép đo,
  `text` cho model/trạng thái, `ok/error` cho trạng thái.
- **`execute_action()`**: ánh xạ một action sang lời gọi driver tương ứng.
- Hỗ trợ **dừng giữa chừng** qua `stop_flag` (nút STOP ở GUI).

---

## 3. `core/scenario_export.py` — Xuất kết quả

Xuất danh sách `StepResult` ra file.

- **CSV** (`.csv`): luôn dùng được, encoding `UTF-8-SIG` để Excel hiển thị tiếng
  Việt đúng.
- **Excel** (`.xlsx`): khối thông tin đầu (kịch bản, chế độ, thời gian, tổng số/số
  lỗi) + bảng tô màu **OK (xanh)/LỖI (đỏ)**, cố định tiêu đề. Tự tắt nếu thiếu
  `openpyxl`.
- **`export()`**: tự chọn định dạng theo đuôi file.

---

## 4. `core/discovery.py` — Phát hiện & nhận diện thiết bị

Giúp gán địa chỉ VISA mà không cần gõ tay (xem GUI Device Manager).

- **`scan_resources()`**: liệt kê mọi địa chỉ VISA (mock trả `MOCK_TOPOLOGY`).
- **`identify_resource()`**: gửi `*IDN?` (timeout ngắn, nuốt lỗi an toàn).
- **`match_driver()`**: khớp chuỗi `*IDN?` với `DEVICE_REGISTRY` qua `IDN_KEYWORDS`.
- **`scan_and_identify()`**: gộp quét + IDN + khớp → `list[DiscoveredDevice]`.
- **Wizard cắm-từng-máy**: `snapshot_resources()` + `diff_new_resources()` để biết
  địa chỉ vừa xuất hiện (cho máy đời cũ không có `*IDN?` hoặc 2 máy trùng model).
- **`test_connection()`**: mở driver tại địa chỉ, thử `identify()`, báo OK/lỗi.

---

## 5. `core/profile.py` — Profile kết nối

Bản đồ thiết bị↔địa chỉ VISA do phần mềm tự sinh (không gõ tay).

- **`ProfileEntry`**: `model_key` + `address` + nhãn thân thiện + serial + idn.
- **`ConnectionProfile`**: tập entry; `address_map()` quy đổi sang
  `{model_key: address}` truyền thẳng cho `ScenarioRunner` khi chạy REAL;
  `save_json()` / `load_json()`; `warnings()` cảnh báo trùng địa chỉ/model.

---

## 6. Ví dụ dùng nhanh (không GUI)

```python
from core import Scenario, ScenarioStep, ScenarioRunner

scn = Scenario(name="Demo", steps=[
    ScenarioStep(action="identify", devices=["CNT91", "N1913A"]),
    ScenarioStep(action="set_gate_time", devices=["CNT91"], params={"gate_time": 0.1}),
    ScenarioStep(action="measure_frequency", devices=["CNT91"]),
    ScenarioStep(action="measure_power", devices=["N1913A"]),
])
results = ScenarioRunner(mock=True).run(scn)
for r in results:
    print(r.summary())
```
