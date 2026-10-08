"""
unit_test/test_widgets.py
============================
Test gui/widgets.py::confirm_yes_no() — BUG-23 (lẫn tiếng Anh): Qt không có
sẵn bản dịch tiếng Việt nên QMessageBox.question(...,
QMessageBox.Yes | QMessageBox.No) hiện "Yes"/"No" tiếng Anh dù phần còn lại
của hộp thoại toàn tiếng Việt. confirm_yes_no() dùng nút chữ Việt tay ("Có"/
"Không"), thay cho MỌI chỗ hỏi Có/Không trong app.

Không thể gọi exec_() thật (modal, treo test chờ click) — monkeypatch
exec_() để tự "bấm" nút mặc định rồi trả về ngay, giống cách
unit_test/test_scenario_grid.py xử lý QMessageBox.warning modal.
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QMessageBox

from gui.widgets import confirm_yes_no

_app = QApplication.instance() or QApplication([])


def _click_default_button(monkeypatch):
    def fake_exec(self):
        self.defaultButton().click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)


def test_confirm_yes_no_buttons_are_vietnamese(monkeypatch):
    captured = {}

    def fake_exec(self):
        captured["texts"] = sorted(b.text() for b in self.buttons())
        self.defaultButton().click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)

    confirm_yes_no(None, "Tiêu đề", "Nội dung")
    assert captured["texts"] == ["Có", "Không"]


def test_confirm_yes_no_default_yes_clicked_returns_true(monkeypatch):
    _click_default_button(monkeypatch)
    assert confirm_yes_no(None, "T", "msg", default_yes=True) is True


def test_confirm_yes_no_default_no_clicked_returns_false(monkeypatch):
    _click_default_button(monkeypatch)
    assert confirm_yes_no(None, "T", "msg", default_yes=False) is False


def test_confirm_yes_no_explicit_no_click_returns_false(monkeypatch):
    """Bấm nút "Không" dù default là "Có" -> vẫn trả False (đọc đúng nút
    THẬT được bấm, không phải suy ra từ default)."""
    def fake_exec(self):
        btn_no = next(b for b in self.buttons() if b.text() == "Không")
        btn_no.click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    assert confirm_yes_no(None, "T", "msg", default_yes=True) is False
