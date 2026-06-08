# Hướng dẫn cài đặt môi trường (Windows)

Tài liệu này hướng dẫn cài đặt phần mềm **freq_calibration** trên một máy tính
Windows mới (bàn giao). Có **3 lớp phụ thuộc tách biệt** — copy source code **không**
tự động cài bất kỳ lớp nào:

| Lớp | Thành phần | Bắt buộc khi nào |
| :-- | :-- | :-- |
| 1. Python | Trình thông dịch Python 3.x | Luôn cần |
| 2. Thư viện Python | `pyvisa`, `PyQt5`, `pandas`, ... (`requirements.txt`) | Luôn cần (kể cả chạy mock) |
| 3. Driver phần cứng / VISA | **NI-VISA** + **NI-488.2** (cho NI GPIB-USB-HS) | Chỉ cần khi nối **thiết bị thật** |

> ⚠️ Quan trọng: `pyvisa` (lớp 2) chỉ là *lớp vỏ Python*. Nó cần một **VISA backend**
> ở cấp hệ điều hành (NI-VISA, lớp 3) để nói chuyện với GPIB. NI-VISA **không** nằm
> trong source code, phải cài riêng. Chế độ **mock** không cần lớp 3.

---

## Bước 1 — Cài Python 3.x

1. Tải Python 3.10+ (khuyến nghị 3.11/3.12) tại <https://www.python.org/downloads/windows/>.
2. Khi cài, **tích "Add python.exe to PATH"**.
3. Kiểm tra:

   ```powershell
   python --version
   pip --version
   ```

---

## Bước 2 — Cài thư viện Python

Mở **PowerShell** tại thư mục source (chứa `main.py`).

(Khuyến nghị) Tạo môi trường ảo để không đụng Python hệ thống:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Nếu PowerShell chặn script kích hoạt venv, chạy 1 lần:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

Cài phụ thuộc:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra import OK:

```powershell
python -c "import pyvisa, PyQt5, pandas; print('Thu vien Python: OK')"
```

### Chạy thử KHÔNG cần phần cứng (mock)

Tới đây đã chạy được test mô phỏng (không cần lớp 3):

```powershell
pytest unit_test -q
```

Kỳ vọng: tất cả test **passed**. Nếu thấy `ModuleNotFoundError: pytest` thì
`pip install -r requirements.txt` chưa chạy hoặc chưa kích hoạt đúng venv.

---

## Bước 3 — Cài driver phần cứng (NI-VISA) — chỉ khi nối thiết bị thật

Cần cho bộ chuyển **NI GPIB-USB-HS** và mọi giao tiếp GPIB.

1. Tải **NI-VISA** tại <https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html>
   (bộ cài này thường kèm luôn **NI-488.2** cho GPIB; nếu không, cài thêm
   **NI-488.2** riêng).
2. Cài đặt, **khởi động lại máy** nếu được yêu cầu.
3. Cắm bộ NI GPIB-USB-HS vào cổng USB và nối cáp GPIB tới thiết bị.
4. Mở **NI MAX** (Measurement & Automation Explorer) →
   *Devices and Interfaces* → kiểm tra thấy adapter GPIB và (Scan Instruments)
   thấy địa chỉ thiết bị (vd `GPIB0::7::INSTR`).

Kiểm tra pyvisa nhìn thấy thiết bị:

```powershell
python -c "import pyvisa; rm = pyvisa.ResourceManager(); print(rm.list_resources())"
```

Kỳ vọng: in ra danh sách địa chỉ VISA, ví dụ `('GPIB0::7::INSTR', ...)`.
Nếu báo `Could not find VISA library` → NI-VISA chưa cài hoặc cài lỗi.

---

## Bước 4 — Chạy với phần cứng thật

### Cách 1 (KHUYẾN NGHỊ cho người dùng cuối): dùng Device Manager trong app

Không cần gõ tay địa chỉ VISA. Trong app → mở **🧩 SCENARIO BUILDER** →
**🔌 Quản lý thiết bị**:

1. Bỏ tick **MOCK**, bấm **🔍 Scan & Identify** → phần mềm tự quét, gửi `*IDN?`
   và tự khớp model cho từng địa chỉ.
2. Máy đời cũ không tự khai báo (Advantest R5372P, Boonton 4231A) hoặc 2 máy
   trùng model → bấm **🔌 Wizard cắm-từng-máy**: làm theo hướng dẫn cắm **một**
   máy, phần mềm phát hiện địa chỉ vừa xuất hiện; bạn chỉ chọn model + đặt tên.
3. Bấm **🧪 Test** từng dòng để xác nhận kết nối (✅/❌).
4. **💾 Lưu profile** → file `connection_profile.json`. Lần sau **📂 Nạp profile**
   là dùng lại ngay. Bấm **✔ Áp dụng** rồi **▶ CHẠY** kịch bản ở chế độ REAL.

### Cách 2 (cho kỹ thuật/CI): chạy pytest trên phần cứng thật

1. Copy file mẫu địa chỉ và điền địa chỉ VISA thật (xem trong NI MAX, hoặc lấy
   từ `connection_profile.json` đã tạo ở Cách 1). Máy không liệt kê sẽ bị **SKIP**.

   ```powershell
   Copy-Item unit_test\addresses.example.json unit_test\addresses.json
   notepad unit_test\addresses.json
   ```

2. Chạy test kết nối / điều khiển / thu thập trên thiết bị thật:

   ```powershell
   pytest unit_test --real --addr-file unit_test\addresses.json -v
   ```

3. Chạy ứng dụng giao diện:

   ```powershell
   python main.py
   ```

---

## Tham chiếu nhanh các chế độ chạy

| Mục đích | Lệnh | Cần lớp 3 (NI-VISA)? |
| :-- | :-- | :-- |
| Test mô phỏng toàn bộ thiết bị | `pytest unit_test -q` | Không |
| Test 2 driver gốc (mock) | `python unit_test\test_connectivity.py --mock` | Không |
| Test trên phần cứng thật | `pytest unit_test --real --addr-file unit_test\addresses.json` | **Có** |
| Chạy GUI | `python main.py` | Có (nếu thao tác máy thật) |

---

## Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách khắc phục |
| :-- | :-- | :-- |
| `ModuleNotFoundError: No module named 'pyvisa'` (hoặc PyQt5/pandas) | Chưa cài lớp 2 | `pip install -r requirements.txt` (đúng venv) |
| `Could not find VISA library` / `VISA library not found` | Chưa cài NI-VISA (lớp 3) | Cài NI-VISA, khởi động lại |
| `rm.list_resources()` trả về rỗng `()` | Adapter chưa nhận / cáp lỏng / chưa scan | Kiểm tra NI MAX, cắm lại USB-GPIB |
| `VisaIOError: Timeout` khi đo | Gate time/averaging dài hoặc địa chỉ sai | Tăng timeout, kiểm tra địa chỉ VISA |
| Thiết bị đời cũ (Advantest R5372P, Boonton 4231A, PM6680) sai lệnh | Tập lệnh hiện là **best-effort**, đánh dấu `TODO(hardware)` trong driver | Đối chiếu manual, chỉnh các hằng `CMD_*` trong file driver tương ứng |
| PowerShell không chạy được `Activate.ps1` | Execution policy | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |

---

## Ghi chú về bàn giao / đóng gói

- **Đóng gói `.exe` (PyInstaller)**: gói được lớp 1 + 2 vào một file, **nhưng KHÔNG
  gói được NI-VISA** (lớp 3). Máy đích vẫn phải cài NI-VISA riêng để dùng GPIB.
- **Backend thay thế `pyvisa-py`** (pure Python, đã có trong `requirements.txt`):
  có thể dùng cho **TCPIP/USB** mà không cần NI-VISA. Nhưng với **GPIB qua
  NI GPIB-USB-HS thì gần như vẫn cần NI-VISA / NI-488.2**.
- **Phương án từ xa (Tailscale + VISA-over-IP)**: chỉ máy *cắm thiết bị* cần
  NI-VISA; máy chạy phần mềm có thể dùng địa chỉ dạng
  `TCPIP0::<ip>::gpib0,<addr>::INSTR` và không cần cài driver GPIB.

---

## Tóm tắt checklist máy mới

- [ ] Cài Python 3.x (Add to PATH)
- [ ] `pip install -r requirements.txt`
- [ ] `pytest unit_test -q` → pass (xác nhận lớp 1 + 2 OK)
- [ ] Cài NI-VISA + NI-488.2 *(chỉ khi cần thiết bị thật)*
- [ ] NI MAX thấy thiết bị → điền `unit_test\addresses.json`
- [ ] `pytest unit_test --real --addr-file unit_test\addresses.json` → pass
