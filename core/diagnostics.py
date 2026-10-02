"""
core/diagnostics.py
=====================
Gom log + thông tin hệ thống thành 1 file .zip để khách hàng gửi lại cho dev
khi gặp sự cố (đặc biệt RAM tăng bất thường) — app chạy offline tại máy
khách, dev không có cách nào truy cập từ xa hay "phone home" tự động, nên
cần 1 nút bấm đơn giản gom mọi manh mối lại thành 1 file duy nhất.

Nội dung file .zip:
  - system_info.txt : phiên bản app, RAM hiện tại, OS, Python, thời điểm xuất.
  - app.log, app.log.1, app.log.2 (nếu có) : toàn bộ log đã ghi (xem
    core/app_logging.py) — bao gồm các dòng "[RAM] ..." ghi định kỳ/sau mỗi
    thao tác tốn RAM, giúp thấy được xu hướng tăng theo thời gian/thao tác.
"""

from __future__ import annotations

import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from core.app_logging import LOG_DIR
from core.paths import get_app_version
from core.ram_monitor import get_process_memory_mb


def _system_info_text() -> str:
    return "\n".join([
        f"Thời điểm xuất: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Phiên bản app: {get_app_version()}",
        f"RAM hiện tại (Working Set): {get_process_memory_mb():.1f} MB",
        f"Hệ điều hành: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"Chạy từ bản đóng gói (PyInstaller): {getattr(sys, 'frozen', False)}",
    ]) + "\n"


def export_diagnostic_bundle(output_path) -> Path:
    """Gom log + thông tin hệ thống thành 1 file .zip tại output_path."""
    output_path = Path(output_path)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system_info.txt", _system_info_text())
        if LOG_DIR.exists():
            for log_file in sorted(LOG_DIR.glob("app.log*")):
                zf.write(log_file, arcname=log_file.name)
    return output_path
