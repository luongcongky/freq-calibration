"""
core/paths.py
==============
Đường dẫn gốc dữ liệu cạnh app (templates/, scenarios/) — dùng chung cho mọi
module cần đọc/ghi các thư mục này.

Khi chạy từ source: gốc project (thư mục chứa main.py), suy ra bằng
Path(__file__).parent.parent như các module vẫn làm trước đây.

Khi chạy bản đóng gói (PyInstaller onedir, sys.frozen=True): PyInstaller gom
hết code vào _internal/, nên __file__ của mọi module lúc đó nằm TRONG
_internal/ (ví dụ _internal/core/paths.py) — suy luận "đi lên N cấp cha" như
lúc chạy từ source sẽ trỏ NHẦM vào trong _internal/ chứ không phải thư mục
chứa .exe (nơi build.ps1 thực sự copy templates/, scenarios/ sang). Phải
suy theo Path(sys.executable).parent thay vào đó.
"""

from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_BASE_DIR = Path(sys.executable).parent
else:
    APP_BASE_DIR = Path(__file__).parent.parent

TEMPLATES_DIR = APP_BASE_DIR / "templates"
SCENARIOS_DIR = APP_BASE_DIR / "scenarios"
