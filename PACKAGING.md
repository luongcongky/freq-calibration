# Đóng gói & bàn giao cho khách hàng

Tài liệu này dành cho **người đóng gói** (dev build bản giao khách), tách rõ
ranh giới: cái gì khách hàng nhận được, cái gì chỉ người đóng gói thao tác.

---

## 1. Khách hàng nhận cái gì?

**CHỈ DUY NHẤT** thư mục (hoặc file `.zip`) trong `release\freq-calibration-vX.Y.Z\`
— thư mục này do `build.ps1` tự sinh ra, **không commit vào git** (đã có trong
`.gitignore`). Bên trong gồm:

```
release/freq-calibration-v1.0.0/
├── freq-calibration.exe          # double-click để chạy, không cần cài Python
├── _internal/                    # thư viện PyInstaller đóng gói kèm
├── scenarios/                    # kịch bản đo mẫu
├── templates/                    # mẫu báo cáo
├── Huong_dan_su_dung_freq_calibration.docx   # tài liệu hướng dẫn đầy đủ
├── 0_DOC_TRUOC_KHI_CHAY.txt      # hướng dẫn nhanh (không cần dòng lệnh)
└── BUILD_INFO.txt                # phiên bản + commit + ngày build (để đối chiếu khi khách báo lỗi)
```

Khách hàng **không bao giờ cần mở PowerShell/CLI** — chỉ giải nén `.zip` rồi
double-click `freq-calibration.exe`. Nếu dùng thiết bị đo thật, khách cần cài
thêm **NI-VISA** (bộ cài `.exe` thông thường của Windows, không phải dòng lệnh)
— hướng dẫn tải đã có trong `0_DOC_TRUOC_KHI_CHAY.txt`.

---

## 2. Người đóng gói giữ lại gì (không gửi khách)?

Toàn bộ phần còn lại của repo: `main.py`, `core/`, `gui/`, `drivers/`,
`unit_test/`, `scripts/`, `requirements.txt`, `build.ps1`,
`freq-calibration.spec`, `VERSION`, `packaging/`, thư mục `dist/` (bản build
trung gian của PyInstaller — thiếu `templates/`, docx, không dùng để giao
khách).

---

## 3. Quy trình ra bản build mới

1. Sửa code, test bằng `pytest unit_test -q` cho tới khi pass.
2. Mở file [VERSION](VERSION), tăng số phiên bản (semver, ví dụ `1.0.0` →
   `1.1.0`).
3. Chạy:

   ```powershell
   .\build.ps1 -Zip
   ```

   Script tự: build PyInstaller → lắp thư mục `release\freq-calibration-v<VERSION>\`
   (kèm `scenarios/`, `templates/`, tài liệu, `BUILD_INFO.txt`) → nén thành
   `release\freq-calibration-v<VERSION>.zip`.
4. Mở thử `release\freq-calibration-v<VERSION>\freq-calibration.exe` để kiểm
   tra chạy được (chế độ MOCK là đủ, không cần cắm máy thật).
5. Gửi file `.zip` đó cho khách. Không gửi thư mục `dist\` hay bất kỳ file
   nào khác trong repo.

Muốn sửa nội dung hướng dẫn nhanh cho khách → sửa
[packaging/CUSTOMER_README.txt](packaging/CUSTOMER_README.txt) (build.ps1 tự
copy sang, đổi tên thành `0_DOC_TRUOC_KHI_CHAY.txt` trong bản release).

---

## 4. Ghi chú

- `freq-calibration.spec` ở gốc repo là artefact PyInstaller sinh tự động từ
  lần chạy thủ công trước đây — `build.ps1` hiện KHÔNG dùng file này (gọi
  `pyinstaller` trực tiếp bằng cờ dòng lệnh), có thể xoá nếu không cần đối
  chiếu.
- NI-VISA (lớp driver GPIB) không đóng gói được — xem chi tiết trong
  [INSTALL.md](INSTALL.md) mục "Ghi chú về bàn giao / đóng gói".
