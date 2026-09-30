"""
core/ram_monitor.py
=====================
Đo RAM (Working Set) của chính tiến trình app — dùng bởi:
  - gui/session_manager.py, gui/scenario_grid.py: ghi log định kỳ + sau các
    thao tác tốn RAM (chạy kịch bản, xuất báo cáo) để dev đọc lại qua file
    log khi khách hàng báo sự cố (app chạy offline, dev không truy cập
    từ xa được — xem core/app_logging.py).
  - core/diagnostics.py: in vào file chẩn đoán xuất ngay lúc khách bấm nút.

Dùng pywin32 (đã là dependency sẵn có của app — xem requirements.txt) qua
GetProcessMemoryInfo (tương đương PROCESS_MEMORY_COUNTERS của Win32 API),
thay vì thêm psutil làm dependency mới.
"""

from __future__ import annotations

import ctypes

import win32api
import win32process


def get_process_memory_mb() -> float:
    """RAM (Working Set) hiện tại của tiến trình app, đơn vị MB."""
    info = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
    return info["WorkingSetSize"] / (1024 * 1024)


def trim_working_set() -> None:
    """Yêu cầu Windows thu hồi ngay các trang RAM đã free nhưng tiến trình
    còn giữ trong Working Set (EmptyWorkingSet, psapi.dll) — gọi sau 1 thao
    tác tốn RAM vừa xong (đóng Scenario Builder, Xem nhanh...).

    Windows KHÔNG tự trả trang heap đã free về OS ngay (đặc điểm quản lý bộ
    nhớ chuẩn của Windows, không phải lỗi của app) — Working Set đo bằng
    Task Manager/Get-Process chỉ giảm khi OS tự dọn (không đoán được lúc
    nào) hoặc khi gọi hàm này. Đây là nguyên nhân chính của hiện tượng
    khách báo "RAM tăng đột xuất, chỉ giảm bất chợt" (REG-RAM-01/02): sau
    khi đóng Scenario Builder/chạy Xem nhanh, object Python/Qt thật ra ĐÃ
    được giải phóng ở tầng heap, chỉ là Windows chưa báo cáo lại số liệu.
    Không ảnh hưởng hiệu năng kế tiếp — trang bị thu hồi sẽ được cấp phát
    lại bình thường nếu app cần dùng tiếp (chỉ tốn thêm vài ms page fault).
    Best-effort: lỗi (nếu có) chỉ bỏ qua, không được làm crash app."""
    try:
        ctypes.windll.psapi.EmptyWorkingSet(win32api.GetCurrentProcess())
    except Exception:  # noqa: BLE001
        pass
