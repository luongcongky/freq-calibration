"""
gui/file_dialog_utils.py
=========================
Wrapper quanh QFileDialog.getOpenFileName/getSaveFileName: nhớ thư mục vừa
dùng gần nhất (dùng CHUNG 1 giá trị cho mọi hộp thoại trong app) và lưu qua
QSettings để giữ được cả sau khi tắt/mở lại app.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QFileDialog

_ORG = "FreqCalibration"
_APP = "freq-calibration"
_KEY_LAST_DIR = "file_dialog/last_dir"


def _get_last_dir() -> str:
    d = QSettings(_ORG, _APP).value(_KEY_LAST_DIR, "", type=str)
    return d if d and os.path.isdir(d) else ""


def _remember_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and os.path.isdir(d):
        QSettings(_ORG, _APP).setValue(_KEY_LAST_DIR, d)


def _resolve_start(directory: str) -> str:
    last_dir = _get_last_dir()
    if not last_dir:
        return directory
    if not directory:
        return last_dir
    if os.path.isdir(directory):
        # directory truyền vào là 1 thư mục mặc định cứng (vd scenarios/) ->
        # ưu tiên thư mục người dùng vừa dùng gần nhất thay cho mặc định này.
        return last_dir
    # directory là tên file gợi ý (có thể kèm đường dẫn) -> giữ tên file,
    # đổi sang thư mục vừa dùng.
    return os.path.join(last_dir, os.path.basename(directory))


def get_open_file_name(parent, caption: str = "", directory: str = "", filter: str = ""):
    path, selected_filter = QFileDialog.getOpenFileName(
        parent, caption, _resolve_start(directory), filter)
    if path:
        _remember_dir(path)
    return path, selected_filter


def get_save_file_name(parent, caption: str = "", directory: str = "", filter: str = ""):
    path, selected_filter = QFileDialog.getSaveFileName(
        parent, caption, _resolve_start(directory), filter)
    if path:
        _remember_dir(path)
    return path, selected_filter
