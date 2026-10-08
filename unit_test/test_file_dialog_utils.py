"""
unit_test/test_file_dialog_utils.py
======================================
Test gui/file_dialog_utils.py — BUG-23: đường dẫn kịch bản lúc hiện "\\"
lúc hiện "/". QFileDialog.getOpenFileName/getSaveFileName luôn trả về "/"
(quy ước nội bộ Qt) trong khi đường dẫn mặc định của mẫu dựng qua pathlib
lại ra "\\" trên Windows — 2 nguồn khác định dạng cho CÙNG 1 khái niệm
"đường dẫn file". get_open_file_name/get_save_file_name phải chuẩn hoá về
đúng dấu phân cách hệ điều hành trước khi trả ra ngoài.
"""

import os

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QFileDialog

from gui import file_dialog_utils

_app = QApplication.instance() or QApplication([])


def test_get_open_file_name_normalizes_forward_slashes(monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: ("C:/Users/HELLO/scenarios/a.json", "JSON (*.json)")))
    path, _ = file_dialog_utils.get_open_file_name(None, "Chọn", "", "JSON (*.json)")
    assert path == os.path.normpath("C:/Users/HELLO/scenarios/a.json")
    assert "/" not in path


def test_get_save_file_name_normalizes_forward_slashes(monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: ("C:/Users/HELLO/out/bien_ban.docx", "Word (*.docx)")))
    path, _ = file_dialog_utils.get_save_file_name(None, "Lưu", "", "Word (*.docx)")
    assert path == os.path.normpath("C:/Users/HELLO/out/bien_ban.docx")
    assert "/" not in path


def test_get_open_file_name_returns_empty_string_unchanged_when_cancelled(monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")))
    path, _ = file_dialog_utils.get_open_file_name(None, "Chọn", "", "JSON (*.json)")
    assert path == ""
