"""
gui/theme.py
============
Bảng màu + stylesheet TOÀN CỤC dùng chung cho mọi cửa sổ/dialog của ứng dụng.

Tách riêng (không gắn với màn hình nào) để các module GUI cùng dùng mà không
phụ thuộc lẫn nhau. Áp stylesheet này lên QApplication để MỌI popup hệ thống
(QInputDialog, QMessageBox, QFileDialog, dropdown combobox) đều theo theme tối.
"""

from __future__ import annotations


class Colors:
    """Bảng màu kỹ thuật (engineering dashboard)."""
    BG_WINDOW    = "#121417"
    BG_CARD      = "#1e2126"
    BG_INPUT     = "#111316"
    ACCENT_CYAN  = "#00d1ff"
    ACCENT_GREEN = "#65f08d"
    ACCENT_RED   = "#ff4d4d"
    ACCENT_WARN  = "#ffaa00"
    TEXT_MAIN    = "#ffffff"
    TEXT_DIM     = "#a0a5ad"
    BORDER       = "#2c3038"


def build_global_qss() -> str:
    """Stylesheet toàn cục đặt trên QApplication (theme tối cho mọi popup/dropdown)."""
    C = Colors
    return f"""
        QWidget {{ background-color: {C.BG_WINDOW}; color: {C.TEXT_MAIN};
                   font-family: 'Segoe UI', sans-serif; }}
        QDialog, QMessageBox, QInputDialog, QFileDialog {{
                   background-color: {C.BG_CARD}; color: {C.TEXT_MAIN}; }}
        QLabel {{ background: transparent; color: {C.TEXT_MAIN}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                   background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 4px; padding: 5px; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{
                   background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   selection-background-color: {C.ACCENT_CYAN};
                   selection-color: {C.BG_WINDOW};
                   border: 1px solid {C.BORDER}; outline: none; }}
        QListView, QTreeView, QListWidget {{
                   background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER};
                   selection-background-color: {C.ACCENT_CYAN};
                   selection-color: {C.BG_WINDOW}; }}
        QPushButton {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 6px; padding: 6px 12px; }}
        QPushButton:hover {{ border-color: {C.ACCENT_CYAN}; }}
        QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        QCheckBox {{ color: {C.TEXT_MAIN}; background: transparent; }}
        QScrollBar:vertical {{ background: {C.BG_INPUT}; width: 12px; }}
        QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 6px; }}
        QMenu {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; }}
        QMenu::item:selected {{ background-color: {C.ACCENT_CYAN}; color: {C.BG_WINDOW}; }}
        QToolTip {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; }}
        QStatusBar {{ color: {C.TEXT_DIM}; }}
        QHeaderView::section {{ background-color: {C.BG_CARD}; color: {C.TEXT_DIM};
                   border: none; border-bottom: 2px solid {C.BORDER}; padding: 7px; }}
        QTableWidget {{ background-color: {C.BG_INPUT}; gridline-color: {C.BORDER};
                   border: 1px solid {C.BORDER}; }}
    """
