"""
unit_test/test_ram_monitor.py
================================
Test core/ram_monitor.py — đo RAM (Working Set) của chính tiến trình app,
dùng cho log định kỳ (gui/session_manager.py, gui/scenario_grid.py) + file
chẩn đoán (core/diagnostics.py).
"""

from core.ram_monitor import get_process_memory_mb, trim_working_set


def test_get_process_memory_mb_returns_positive_float():
    mb = get_process_memory_mb()
    assert isinstance(mb, float)
    # Tiến trình Python nào cũng tốn ít nhất vài MB -> chặn dưới an toàn,
    # không chốt chặn trên (phụ thuộc máy chạy test).
    assert mb > 1.0


def test_trim_working_set_does_not_raise():
    """REG-RAM-01/02: gọi sau khi đóng Scenario Builder/Xem nhanh để Working
    Set báo cáo đúng phần vừa giải phóng — best-effort, không được crash
    app dù chạy trên môi trường nào."""
    trim_working_set()
    # Vẫn đọc được RAM bình thường sau khi trim.
    assert get_process_memory_mb() > 1.0
