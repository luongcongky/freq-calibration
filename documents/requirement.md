# Phân tích yêu cầu & Kế hoạch triển khai

> **Cập nhật kiến trúc:** dự án đã chuẩn hoá về **Scenario Builder (grid
> step-by-step, đa thiết bị)** cho mọi nhóm máy. Luồng file `.txt` + dashboard
> SMW200A/CNT-90XL trong mô tả gốc bên dưới **đã được loại bỏ** (giữ lại để tham
> chiếu lịch sử). Xem [README.md](../README.md) và
> [user_action_flow.md](user_action_flow.md) cho trạng thái hiện tại.

## 1. Mục tiêu dự án

Phần mềm tự động kiểm định/hiệu chuẩn **hai nhóm thiết bị** qua GPIB/LAN (VISA):

- **Nhóm máy đếm tần số** cao tần/siêu cao tần: Pendulum (CNT-85/90/91),
  Keysight/HP (531xx, 5322xA, 5315xA, 53147A), Fluke/Philips (PM668x/669x),
  Advantest R5372P.
- **Nhóm máy đo công suất** cao tần: Keysight (E4410A, N1911A/N1913A/N1914A),
  Boonton 4231A.

Bốn chức năng chính:
- Nhận diện & điều khiển thiết bị qua VISA (mỗi model 1 driver chuyên biệt).
- Thu thập dữ liệu đo lường (tại Trung tâm TC-ĐL-CL 2).
- Xử lý & xuất kết quả (Excel/CSV).
- Giao diện dựng kịch bản trực quan dạng grid (không cần lập trình/gõ file lệnh).

**Luồng giao tiếp**: NI GPIB-USB-HS + pyvisa (hoặc VISA-over-IP qua Tailscale/VPN).

---

## 2. Kế hoạch triển khai (Project Roadmap)

### Giai đoạn 1: Thiết lập môi trường & kết nối (1-2 tuần)

- **Cài đặt driver**: Cấu hình NI-VISA + pyvisa, thiết lập NI GPIB-USB-HS và môi trường Python 3.x.
- **Nhận diện thiết bị**: Thực hiện quét GPIB bus, kết nối và nhận diện SMW200A cùng CNT-90XL.
- **Kiểm tra lệnh SCPI**: Thao tác \*IDN? handshake, thử nghiệm lệnh Set freq/power và Read measurement.

### Giai đoạn 2: Xây dựng module điều khiển (2-3 tuần)

- **Driver SMW200A**: Hoàn thiện các hàm Set frequency, Set amplitude, RF on/off và xử lý lỗi (Error handling).
- **Driver CNT-90XL**: Triển khai Measure frequency, cấu hình Trigger & gate time, đọc buffer và tính toán thống kê (mean/std).
- **Parser lệnh .txt**: Xây dựng module đọc sequence file, parse danh sách 5-10 lệnh, thực hiện Validate, logging và vòng lặp đo tự động.

### Giai đoạn 3: Xử lý dữ liệu & xuất báo cáo (1-2 tuần)

- **Thu thập dữ liệu**: Tổ chức dữ liệu qua pandas DataFrame, thực hiện Timestamp logging và chuẩn hóa ký hiệu chuẩn.
- **Xử lý kỹ thuật**: Xây dựng logic so sánh chuẩn, tính toán sai số và độ không đảm bảo (uncertainty).
- **Xuất báo cáo**: Tự động hóa xuất file Excel (openpyxl), Word (docx) theo đúng mẫu chuẩn của TC-ĐL-CL 2.

### Giai đoạn 4: Giao diện & kiểm thử (1-2 tuần)

- **GUI (tkinter/PyQt)**: Thiết kế giao diện cho phép load file lệnh, hiển thị trạng thái thiết bị trực tiếp (Live status) và theo dõi tiến độ (Progress + log).
- **Kiểm thử & Debug**: Thực hiện Mock instrument để test offline, Unit test driver và Integration test toàn hệ thống.
- **Đóng gói & Bàn giao**: Sử dụng PyInstaller để đóng gói thành file `.exe`, chuẩn bị tài liệu hướng dẫn và bàn giao mã nguồn.

## 3. Tech stack gợi ý

- Python 3.x · pyvisa · NI-VISA driver · pandas · openpyxl · python-docx
- tkinter hoặc PyQt5 · PyInstaller · pytest
- Tổng thời gian ước tính: 6–9 tuần

## 4. Tailscale VPN + FastAPI instrument server

Dễ cài, không cần public IP, bảo mật WireGuard, pyvisa kết nối trong suốt qua VISA-over-IP

## 5. Cấu trúc project (thực tế hiện tại)

```
freq_calibration/
├── drivers/                 # Mỗi model 1 driver, chung base_visa.py
│ ├── base_visa.py           #   Lớp transport VISA + mock
│ ├── pendulum_counters.py   #   CNT-85/90/91
│ ├── keysight_counters.py   #   531xx / 5322xA / 5315xA / 53147A
│ ├── fluke_counters.py      #   PM6680 / PM6690
│ ├── advantest_r5372p.py    #   R5372P (legacy)
│ ├── keysight_power.py       #   E4410A / N191xA
│ ├── boonton_4231a.py       #   4231A (legacy)
│ ├── smw200a.py, cnt90xl.py # Driver gốc (giữ lại)
│ └── __init__.py            #   DEVICE_REGISTRY
├── core/                    # Logic (không Qt → test được)
│ ├── scenario.py            #   Mô hình kịch bản grid + JSON + validate
│ ├── scenario_runner.py     #   Thực thi đa thiết bị
│ ├── scenario_export.py     #   Xuất CSV/XLSX
│ ├── discovery.py           #   Quét VISA + *IDN? + wizard
│ └── profile.py             #   Profile kết nối (model→địa chỉ)
├── gui/
│ ├── scenario_grid.py       #   Màn hình chính (Scenario Builder)
│ ├── device_manager.py      #   Quản lý thiết bị
│ └── theme.py               #   Theme dùng chung
├── unit_test/               # pytest (mock)
├── scenarios/               # Kịch bản mẫu (.json)
└── main.py                  # Điểm vào → Scenario Builder
```

> Lưu ý: các module luồng cũ (`sequence.py`, `measurement.py`, `report.py`,
> `simulation.py`, dashboard `gui/app.py`, file `.txt`) đã được loại bỏ; báo cáo
> Word/Excel mẫu TC-ĐL-CL 2 sẽ được khôi phục dưới dạng xuất từ kết quả grid khi
> cần.
