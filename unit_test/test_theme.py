"""
unit_test/test_theme.py
========================
K01 (test_reports/2026-10-09_khong_thiet_bi/BAO_CAO_TEST_KHONG_THIET_BI.md):
bản .exe (PyInstaller) mất mũi tên ▼ ở mọi combo box/ô ngày — build_global_qss()
tính đường dẫn arrow_down.svg từ __file__, nhưng __file__ không phải file thật
trên đĩa khi đóng gói (gui/theme.py chỉ còn bytecode trong PYZ) -> đường dẫn
sai, Qt không load được icon SVG.
"""

import sys

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from gui import theme


def test_arrow_path_uses_file_relative_path_when_not_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    qss = theme.build_global_qss()
    assert "gui/arrow_down.svg" in qss


def test_arrow_path_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "freq-calibration.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    qss = theme.build_global_qss()
    expected = str(tmp_path / "gui" / "arrow_down.svg").replace("\\", "/")
    assert expected in qss, (
        f"Đường dẫn mũi tên không nằm cạnh .exe khi frozen (K01): {qss[:200]!r}")
