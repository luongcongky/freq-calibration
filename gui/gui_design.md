# Thiết kế Giao diện (GUI Design)

Giao diện theo phong cách **Engineering Dashboard** (nền tối, accent cyan), gồm 2
cửa sổ chính + 1 module theme dùng chung. Toàn bộ PyQt5.

> Dashboard `.txt` cũ (SMW200A + CNT-90XL) đã được loại bỏ. Màn hình chính nay là
> **Scenario Builder**.

---

## 1. `gui/theme.py` — Theme dùng chung

- **`Colors`**: bảng màu (BG_WINDOW, BG_CARD, ACCENT_CYAN, ACCENT_GREEN/RED/WARN…).
- **`build_global_qss()`**: stylesheet **toàn cục** đặt lên `QApplication`, đảm bảo
  mọi popup hệ thống (QInputDialog, QMessageBox, QFileDialog và **dropdown của
  combobox**) đều theo theme tối — tránh nền trắng mặc định.

---

## 2. `gui/scenario_grid.py` — Màn hình chính (Scenario Builder)

`ScenarioGridWindow` — nơi dựng và chạy kịch bản grid.

**Bố cục:**
- **Header**: tiêu đề + checkbox **MOCK**.
- **Thanh công cụ**: ➕ Thêm bước · ✏ Sửa · ⧉ Nhân bản · 🗑 Xóa · ▲ ▼ · 🔌 Quản lý
  thiết bị · 📂 Mở · 💾 Lưu · ▶ CHẠY · ■ DỪNG · 📤 Xuất kết quả.
- **Grid** (bảng bước) — 8 cột: Bật · # · Thiết bị · Hành động · Tham số · Ghi chú
  · **Kết quả** · **Trạng thái**.
- **Khung log** live ở dưới + thanh status.

**Hành vi:**
- Double-click một dòng để sửa bước.
- Khi chạy: `ScenarioWorker` (QThread) chạy `ScenarioRunner` nền, phát `StepResult`
  → cập nhật cột Kết quả/Trạng thái và log theo thời gian thực; nút 📤 sáng lên sau
  khi xong.
- Chế độ REAL dùng `address_map` lấy từ Device Manager; thiếu địa chỉ sẽ bị chặn.

**Dialog soạn bước (`StepEditorDialog`):**
- Danh sách thiết bị **chọn nhiều** (checkbox) từ `DEVICE_REGISTRY`.
- Combo **hành động tự lọc** theo nhóm thiết bị đang chọn.
- Form **tham số động** theo `ACTION_SPECS` của hành động.

---

## 3. `gui/device_manager.py` — Quản lý thiết bị

`DeviceManagerDialog` — gán địa chỉ VISA mà không cần gõ tay.

**Ba cơ chế (tự động → thủ công):**
1. **🔍 Scan & Identify**: quét VISA + `*IDN?` + tự khớp driver (chạy nền qua
   `ScanWorker`).
2. **🔌 Wizard cắm-từng-máy**: phát hiện địa chỉ vừa xuất hiện (máy đời cũ / trùng
   model).
3. **🧪 Test** mỗi dòng: mở driver thật, `identify()`, báo ✅/❌.

**Bảng:** Địa chỉ VISA · *IDN?* · Nhận diện · Gán model (combo) · Tên gợi nhớ ·
Serial · Kiểm tra · Trạng thái.

**Profile:** 💾 Lưu / 📂 Nạp `connection_profile.json`; **✔ Áp dụng** trả
`ConnectionProfile` về cho Scenario Builder (→ `address_map`).

---

## 4. Phong cách (Look & Feel)

- Nền tối (dark slate) giảm mỏi mắt cho kỹ thuật viên; accent **cyan** cho dữ liệu,
  **xanh lá** OK, **đỏ** lỗi, **cam** cảnh báo.
- Bảng phẳng (không gridline đậm), tiêu đề cố định, trạng thái tô màu trực quan.
- Thư viện: **PyQt5**. Đóng gói: PyInstaller (xem [INSTALL.md](../INSTALL.md)).
