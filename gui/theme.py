"""
gui/theme.py
============
Bảng màu + stylesheet TOÀN CỤC dùng chung cho mọi cửa sổ/dialog của ứng dụng.

Tách riêng (không gắn với màn hình nào) để các module GUI cùng dùng mà không
phụ thuộc lẫn nhau. Áp stylesheet này lên QApplication để MỌI popup hệ thống
(QInputDialog, QMessageBox, QFileDialog, dropdown combobox) đều theo theme tối.
"""

from __future__ import annotations

import pathlib


class Colors:
    """Bảng màu kỹ thuật (engineering dashboard).

    Phân cấp độ sáng từ tối → sáng:
      BG_DEEP → BG_INPUT → BG_WINDOW → BG_SURFACE → BG_CARD → BG_CARD_HI
    """
    # ── Nền (từ tối nhất → sáng nhất) ────────────────────────────────────
    BG_DEEP      = "#080b10"   # Log / terminal (tối nhất — recessed)
    BG_INPUT     = "#0c0f18"   # Input field, table (recessed)
    BG_WINDOW    = "#111520"   # Nền cửa sổ chính
    BG_SURFACE   = "#171e30"   # Header, toolbar strips (chrome)
    BG_CARD      = "#1c2438"   # Tab pane, content panel
    BG_CARD_HI   = "#21304a"   # GroupBox, elevated card

    # ── Accent ────────────────────────────────────────────────────────────
    ACCENT_CYAN    = "#00d1ff"
    ACCENT_GREEN   = "#65f08d"
    ACCENT_RED     = "#ff4d4d"
    ACCENT_WARN    = "#ffaa00"
    ACCENT_MAGENTA = "#ff4fd8"   # nổi bật riêng cho bước ghi báo cáo (report_val)

    # ── Text ──────────────────────────────────────────────────────────────
    TEXT_MAIN    = "#e8ecf4"   # Trắng ngà (dễ đọc hơn trắng thuần)
    TEXT_DIM     = "#7a8aa8"

    # ── Border ────────────────────────────────────────────────────────────
    BORDER       = "#28364e"   # Blue-navy tint


def build_global_qss() -> str:
    """Stylesheet toàn cục đặt trên QApplication (theme tối cho mọi popup/dropdown)."""
    C = Colors
    # Đường dẫn tuyệt đối tới file SVG mũi tên, dùng forward-slash cho Qt
    _arrow_path = str(pathlib.Path(__file__).with_name("arrow_down.svg")).replace("\\", "/")
    return f"""
        QWidget {{ background-color: {C.BG_WINDOW}; color: {C.TEXT_MAIN};
                   font-family: 'Segoe UI', sans-serif; }}
        QDialog, QMessageBox, QInputDialog, QFileDialog {{
                   background-color: {C.BG_CARD}; color: {C.TEXT_MAIN}; }}
        QLabel {{ background: transparent; color: {C.TEXT_MAIN}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                   background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 4px; padding: 5px; }}
        QComboBox::drop-down {{ border: none; border-left: 1px solid {C.BORDER};
                   width: 24px; background: transparent; }}
        QComboBox::down-arrow {{ image: url("{_arrow_path}"); width: 10px; height: 6px; }}
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
        /* selection-background-color/selection-color ở trên chỉ chắc chắn
           áp dụng khi widget đang có FOCUS — khi focus rời sang nơi khác
           (vd bấm 1 nút), Qt vẽ dòng đang chọn theo màu "inactive" mặc định
           (nhạt/gần như mất hẳn màu). Khai rõ ::item:selected:!active để
           dòng đang chọn LUÔN giữ màu sáng dù đã mất focus. */
        QListWidget::item:selected, QListWidget::item:selected:!active {{
                   background-color: {C.ACCENT_CYAN}; color: {C.BG_WINDOW}; }}
        QTreeWidget::item:selected {{
                   background-color: #0e6080; color: {C.TEXT_MAIN}; }}
        QTreeWidget::item:selected:!active {{
                   background-color: #0a3f52; color: {C.TEXT_DIM}; }}
        QTreeWidget::item:hover:!selected {{
                   background-color: #1a2830; }}
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
                   border: none; border-bottom: 2px solid {C.BORDER};
                   border-right: 1px solid {C.BORDER}; padding: 7px; }}
        QTableWidget {{ background-color: {C.BG_INPUT}; gridline-color: {C.BORDER};
                   border: 1px solid {C.BORDER};
                   selection-background-color: {C.ACCENT_CYAN};
                   selection-color: {C.BG_WINDOW}; }}

        /* ── Tab widget ── */
        QTabWidget::pane {{ border: 1px solid {C.BORDER};
                   background-color: {C.BG_CARD}; top: -1px; }}
        QTabBar::tab {{ background-color: {C.BG_SURFACE}; color: {C.TEXT_DIM};
                   border: 1px solid {C.BORDER}; border-bottom: none;
                   padding: 8px 20px; border-radius: 4px 4px 0 0; min-width: 130px; }}
        QTabBar::tab:selected {{ background-color: {C.BG_CARD}; color: {C.ACCENT_CYAN};
                   border-bottom: 2px solid {C.ACCENT_CYAN}; font-weight: bold; }}
        QTabBar::tab:hover:!selected {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN}; }}

        /* ── GroupBox ── */
        QGroupBox {{ background-color: {C.BG_CARD_HI}; border: 1px solid {C.BORDER};
                   border-radius: 6px; margin-top: 14px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
                   left: 12px; padding: 0 6px;
                   color: {C.ACCENT_CYAN}; font-weight: bold; }}

        /* ── Date / Progress / Splitter ── */
        QDateEdit {{ background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 4px; padding: 5px; }}
        QDateEdit::drop-down {{ border: none; border-left: 1px solid {C.BORDER};
                   width: 24px; background: transparent; }}
        QProgressBar {{ background-color: {C.BG_INPUT}; border: 1px solid {C.BORDER};
                   border-radius: 4px; text-align: center; color: {C.TEXT_MAIN}; }}
        QProgressBar::chunk {{ background-color: {C.ACCENT_CYAN}; border-radius: 3px; }}
        QSplitter::handle {{ background-color: {C.BORDER}; width: 1px; }}

        /* ── Layout-section frames ── */
        QFrame#app_header {{
            background-color: {C.BG_SURFACE};
            border-bottom: 2px solid {C.ACCENT_CYAN};
        }}
        QFrame#app_toolbar {{
            background-color: {C.BG_SURFACE};
            border-bottom: 1px solid {C.BORDER};
        }}
        QFrame#log_panel {{
            background-color: {C.BG_DEEP};
            border-top: 1px solid {C.BORDER};
        }}
        QFrame#log_panel QLabel {{
            background: transparent;
            color: {C.TEXT_DIM};
            font-size: 10px;
        }}
        QFrame#log_panel QPushButton {{
            background: transparent;
            border: none;
            color: {C.TEXT_DIM};
            padding: 2px 6px;
        }}
        QFrame#log_panel QPushButton:hover {{ color: {C.TEXT_MAIN}; }}
        QTextEdit#log_console {{
            background-color: {C.BG_DEEP};
            color: {C.ACCENT_GREEN};
            border: none;
            font-family: Consolas, 'Courier New', monospace;
            font-size: 10px;
        }}

        /* ── Content area inside tab panes / scroll areas ── */
        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
    """
