"""
unit_test/test_app_logging.py
================================
Test core/app_logging.py::setup_logging() — cấu hình ghi log ra file xoay
vòng cạnh app (trước đây app KHÔNG ghi log ra file nào, chỉ in ra console —
vô dụng khi chẩn đoán sự cố ở máy khách hàng, nơi dev không có console/
quyền truy cập từ xa).

Logging là state TOÀN CỤC (root logger) -> test phải tự lưu/khôi phục lại
handler gốc sau khi chạy, tránh ảnh hưởng tới các test khác chạy sau.
"""

import logging

import core.app_logging as app_logging


def test_setup_logging_creates_rotating_file_and_writes_to_it(tmp_path, monkeypatch):
    log_dir = tmp_path / "data"
    log_path = log_dir / "app.log"
    monkeypatch.setattr(app_logging, "LOG_DIR", log_dir)
    monkeypatch.setattr(app_logging, "LOG_PATH", log_path)

    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        app_logging.setup_logging()
        logging.getLogger("test_app_logging").info("dong log thu nghiem")
        for h in root.handlers:
            h.flush()

        assert log_path.is_file()
        assert "dong log thu nghiem" in log_path.read_text(encoding="utf-8")
    finally:
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)
        for h in old_handlers:
            root.addHandler(h)
        root.setLevel(old_level)
