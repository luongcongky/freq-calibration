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

import win32api
import win32process


def get_process_memory_mb() -> float:
    """RAM (Working Set) hiện tại của tiến trình app, đơn vị MB."""
    info = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
    return info["WorkingSetSize"] / (1024 * 1024)
