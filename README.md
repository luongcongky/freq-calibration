# freq_calibration — Phần mềm kiểm định/hiệu chuẩn tần số & công suất

Phần mềm điều khiển, thu thập và xử lý số liệu để **tự động kiểm định/hiệu chuẩn**
hai nhóm thiết bị qua GPIB/LAN (VISA):

- **Nhóm máy đếm tần số** (cao tần / siêu cao tần)
- **Nhóm máy đo công suất** cao tần

Người dùng dựng kịch bản đo dạng **grid step-by-step**, kết hợp nhiều thiết bị
trong cùng một bài, chạy và xuất kết quả — không cần lập trình.

> Lịch sử: bản đầu dùng file lệnh `.txt` cho cặp SMW200A + CNT-90XL. Kiến trúc
> hiện tại đã **chuẩn hoá hoàn toàn về Scenario Builder (grid)** cho mọi loại máy;
> luồng `.txt` đã được loại bỏ.

---

## 1. Thiết bị được hỗ trợ

Khai báo tập trung trong `DEVICE_REGISTRY` ([drivers/__init__.py](drivers/__init__.py)).

| Nhóm | Hãng | Model |
| :-- | :-- | :-- |
| Máy đếm tần số | Pendulum | CNT-85, CNT-90, CNT-91 |
| Máy đếm tần số | Keysight/HP | 53131A, 53132A, 53220A, 53150A, 53151A, 53147A |
| Máy đếm tần số | Fluke/Philips | PM6680x, PM6690x |
| Máy đếm tần số | Advantest | R5372P *(legacy, best-effort)* |
| Máy đo công suất | Keysight | E4410A, N1911A, N1913A, N1914A |
| Máy đo công suất | Boonton | 4231A *(legacy, best-effort)* |

> *legacy/best-effort*: máy đời cũ dùng lệnh không phải SCPI — tập lệnh hiện là
> "best-effort", đánh dấu `TODO(hardware)` trong driver, cần đối chiếu manual khi
> chạy máy thật. Driver `SMW200A` (máy phát) và `CNT90XL` (driver Pendulum giàu
> tính năng) vẫn còn trong gói nhưng dùng API riêng, không nằm trong registry.

---

## 2. Kiến trúc

```
freq_calibration/
├── main.py                  # Điểm vào: mở Scenario Builder
├── drivers/                 # Lớp DRIVER thiết bị (mỗi model 1 class)
│   ├── base_visa.py         #   Lớp transport VISA dùng chung (connect/mock/_query)
│   ├── pendulum_counters.py #   CNT-85/90/91
│   ├── keysight_counters.py #   531xx / 5322xA / 5315xA / 53147A
│   ├── fluke_counters.py    #   PM6680 / PM6690
│   ├── advantest_r5372p.py  #   R5372P (legacy)
│   ├── keysight_power.py     #   E4410A / N191xA
│   ├── boonton_4231a.py     #   4231A (legacy)
│   ├── smw200a.py, cnt90xl.py# Driver gốc (giữ lại)
│   └── __init__.py          #   DEVICE_REGISTRY
├── core/                    # Lớp LOGIC (không phụ thuộc Qt → test được)
│   ├── scenario.py          #   Mô hình kịch bản grid + JSON + validate
│   ├── scenario_runner.py   #   Bộ thực thi đa thiết bị (mock/real)
│   ├── scenario_export.py   #   Xuất kết quả CSV/XLSX
│   ├── discovery.py         #   Quét VISA + *IDN? + tự khớp driver + wizard
│   └── profile.py           #   Profile kết nối (model→địa chỉ VISA)
├── gui/                     # Lớp GIAO DIỆN (PyQt5)
│   ├── scenario_grid.py     #   Cửa sổ chính (grid builder + run + export)
│   ├── device_manager.py    #   Quản lý thiết bị (scan/identify/test/profile)
│   └── theme.py             #   Bảng màu + stylesheet toàn cục
├── unit_test/               # pytest (chạy mock, không cần phần cứng)
└── scenarios/               # Kịch bản mẫu (.json)
```

**Nguyên tắc:** logic (`core/`, `drivers/`) tách khỏi GUI nên kiểm thử được bằng
pytest ở chế độ mock; mỗi model là một class driver chuyên biệt, dùng chung lớp
transport `VisaInstrument`.

---

## 3. Cài đặt & chạy

Xem chi tiết từng bước cho Windows tại **[INSTALL.md](INSTALL.md)**. Tóm tắt:

```powershell
pip install -r requirements.txt
python main.py
```

- Mặc định chạy được ngay ở chế độ **MOCK** (không cần phần cứng).
- Để dùng thiết bị thật cần cài **NI-VISA** (xem INSTALL.md), rồi dùng
  **🔌 Quản lý thiết bị** trong app để quét & gán địa chỉ.

---

## 4. Quy trình sử dụng (tóm tắt)

1. `python main.py` → mở **Scenario Builder**.
2. **🔌 Quản lý thiết bị** → **Scan & Identify** (hoặc Wizard cắm-từng-máy) → gán
   model → **Lưu profile**.
3. **➕ Thêm bước**: chọn 1 hoặc nhiều thiết bị + hành động + tham số.
4. **▶ CHẠY** (MOCK hoặc REAL) → kết quả/trạng thái hiện live trên grid.
5. **📤 Xuất kết quả** ra `.xlsx`/`.csv`; **💾 Lưu** kịch bản ra `.json` để tái dùng.

Chi tiết: [documents/user_action_flow.md](documents/user_action_flow.md).

---

## 5. Kiểm thử

```powershell
pytest unit_test -q                                   # toàn bộ test ở mock
pytest unit_test --real --addr-file unit_test\addresses.json   # trên phần cứng thật
```

---

## 6. Tài liệu liên quan

- [INSTALL.md](INSTALL.md) — cài đặt môi trường (Windows, NI-VISA, mock vs real).
- [drivers/GUIDE.md](drivers/GUIDE.md) — chi tiết driver từng nhóm máy.
- [core/GUIDE.md](core/GUIDE.md) — chi tiết module lõi.
- [gui/gui_design.md](gui/gui_design.md) — thiết kế giao diện.
- [documents/user_action_flow.md](documents/user_action_flow.md) — luồng thao tác.
- [documents/requirement.md](documents/requirement.md) — yêu cầu & lộ trình.
