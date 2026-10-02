"""
core/app_logging.py
=====================
Cấu hình logging CHO TOÀN APP — phục vụ chẩn đoán sự cố (đặc biệt RAM tăng
bất thường) ở máy khách hàng, nơi dev KHÔNG có quyền truy cập từ xa. App
chạy offline (phòng đo/Lab thường cách ly mạng) nên không "phone home" được
— thay vào đó ghi lại mọi thứ vào 1 file log cạnh app, khách hàng tự gửi lại
(nguyên file, hoặc qua "Xuất file chẩn đoán" — xem core/diagnostics.py) khi
gặp sự cố.

File log: <APP_BASE_DIR>/data/app.log — RotatingFileHandler, tối đa ~2MB x 3
file xoay vòng (app.log, app.log.1, app.log.2) — đủ dài để thấy xu hướng RAM
tăng dần qua nhiều phiên làm việc, không phình đĩa vô hạn.
"""

from __future__ import annotations

import logging
import logging.handlers

from core.paths import APP_BASE_DIR

LOG_DIR = APP_BASE_DIR / "data"
LOG_PATH = LOG_DIR / "app.log"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Gọi 1 lần ở main.py::main() — vừa in ra console (bản build --console)
    vừa ghi file xoay vòng cạnh app (mọi bản, kể cả --windowed không có
    console nào để xem log)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    # force=True: ghi đè handler gốc nếu đã có (vd thư viện khác lỡ gọi
    # basicConfig trước) — thiếu cờ này, basicConfig() KHÔNG LÀM GÌ CẢ khi
    # root logger đã có sẵn handler, khiến file log không bao giờ được gắn.
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler], force=True)
