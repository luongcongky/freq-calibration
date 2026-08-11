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
    """Bảng màu kỹ thuật (HUD navy/gold — khớp mockup FREQ-CAL PRO).

    Phân cấp độ sáng từ tối → sáng:
      BG_DEEP → BG_INPUT → BG_WINDOW → BG_SURFACE → BG_CARD → BG_CARD_HI
    """
    # ── Nền (từ tối nhất → sáng nhất) ────────────────────────────────────
    BG_DEEP      = "#060b18"   # Log / terminal / status bar (tối nhất — recessed)
    BG_INPUT     = "#0a1020"   # Input field, table (recessed)
    BG_WINDOW    = "#0d1630"   # Nền cửa sổ chính
    BG_SURFACE   = "#080e1e"   # Header, toolbar, sidebar strips (chrome)
    BG_CARD      = "#0a1020"   # Tab pane, content panel
    BG_CARD_HI   = "#111d35"   # GroupBox, elevated card

    # ── Accent ────────────────────────────────────────────────────────────
    ACCENT_PRIMARY = "#ffcc44"   # Vàng gold — accent chính (chọn/active/focus)
    ACCENT_GREEN   = "#44bb66"
    ACCENT_RED     = "#ff5544"
    ACCENT_WARN    = "#ff8844"
    ACCENT_MAGENTA = "#ff4fd8"   # nổi bật riêng cho bước ghi báo cáo (report_val)

    # ── Text ──────────────────────────────────────────────────────────────
    TEXT_MAIN    = "#c9d4ea"   # Ngà xanh nhạt (dễ đọc trên nền navy đậm)
    TEXT_DIM     = "#6a80a8"

    # ── Border ────────────────────────────────────────────────────────────
    BORDER       = "#2a3a5c"   # Blue-navy tint


def build_global_qss() -> str:
    """Stylesheet toàn cục đặt trên QApplication (theme tối cho mọi popup/dropdown)."""
    C = Colors
    # Đường dẫn tuyệt đối tới file SVG mũi tên, dùng forward-slash cho Qt
    _arrow_path = str(pathlib.Path(__file__).with_name("arrow_down.svg")).replace("\\", "/")
    return f"""
        QWidget {{ background-color: {C.BG_WINDOW}; color: {C.TEXT_MAIN};
                   font-family: 'Consolas', 'Courier New', monospace; }}
        QDialog, QMessageBox, QInputDialog, QFileDialog {{
                   background-color: {C.BG_CARD}; color: {C.TEXT_MAIN}; }}
        QLabel {{ background: transparent; color: {C.TEXT_MAIN}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                   background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 0px; padding: 5px; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                   border-color: {C.ACCENT_PRIMARY}; }}
        QComboBox::drop-down {{ border: none; border-left: 1px solid {C.BORDER};
                   width: 24px; background: transparent; }}
        QComboBox::down-arrow {{ image: url("{_arrow_path}"); width: 10px; height: 6px; }}
        QComboBox QAbstractItemView {{
                   background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   selection-background-color: {C.ACCENT_PRIMARY};
                   selection-color: {C.BG_WINDOW};
                   border: 1px solid {C.BORDER}; outline: none; }}
        QListView, QTreeView, QListWidget {{
                   background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER};
                   selection-background-color: {C.ACCENT_PRIMARY};
                   selection-color: {C.BG_WINDOW}; }}
        /* selection-background-color/selection-color ở trên chỉ chắc chắn
           áp dụng khi widget đang có FOCUS — khi focus rời sang nơi khác
           (vd bấm 1 nút), Qt vẽ dòng đang chọn theo màu "inactive" mặc định
           (nhạt/gần như mất hẳn màu). Khai rõ ::item:selected:!active để
           dòng đang chọn LUÔN giữ màu sáng dù đã mất focus. */
        QListWidget::item:selected, QListWidget::item:selected:!active {{
                   background-color: {C.ACCENT_PRIMARY}; color: {C.BG_WINDOW}; }}
        QTreeWidget::item:selected {{
                   background-color: #6a5010; color: {C.TEXT_MAIN}; }}
        QTreeWidget::item:selected:!active {{
                   background-color: #3a3008; color: {C.TEXT_DIM}; }}
        QTreeWidget::item:hover:!selected {{
                   background-color: #16223a; }}
        QPushButton {{ background-color: {C.BG_CARD_HI}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 0px; padding: 6px 12px;
                   font-weight: bold; }}
        QPushButton:hover {{ border-color: {C.ACCENT_PRIMARY}; color: {C.ACCENT_PRIMARY}; }}
        QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        QCheckBox {{ color: {C.TEXT_MAIN}; background: transparent; }}
        QScrollBar:vertical {{ background: {C.BG_INPUT}; width: 12px; }}
        QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 0px; }}
        QMenu {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; }}
        QMenu::item:selected {{ background-color: {C.ACCENT_PRIMARY}; color: {C.BG_WINDOW}; }}
        QToolTip {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; }}
        QStatusBar {{ color: {C.TEXT_DIM}; font-size: 11px; letter-spacing: 1px; }}
        QHeaderView::section {{ background-color: {C.BG_CARD}; color: {C.TEXT_DIM};
                   border: none; border-bottom: 2px solid {C.BORDER};
                   border-right: 1px solid {C.BORDER}; padding: 7px; }}
        QTableWidget {{ background-color: {C.BG_INPUT}; gridline-color: {C.BORDER};
                   border: 1px solid {C.BORDER};
                   selection-background-color: {C.ACCENT_PRIMARY};
                   selection-color: {C.BG_WINDOW}; }}

        /* ── Tab widget ── */
        QTabWidget::pane {{ border: 1px solid {C.BORDER};
                   background-color: {C.BG_CARD}; top: -1px; }}
        QTabBar::tab {{ background-color: {C.BG_SURFACE}; color: {C.TEXT_DIM};
                   border: 1px solid {C.BORDER}; border-bottom: none;
                   padding: 8px 20px; border-radius: 0px; min-width: 130px; }}
        QTabBar::tab:selected {{ background-color: #1e1a08; color: {C.ACCENT_PRIMARY};
                   border-color: #6a5010; border-bottom: 2px solid {C.ACCENT_PRIMARY}; font-weight: bold; }}
        QTabBar::tab:hover:!selected {{ background-color: {C.BG_CARD}; color: {C.TEXT_MAIN}; }}

        /* ── GroupBox ── */
        QGroupBox {{ background-color: {C.BG_CARD_HI}; border: 1px solid {C.BORDER};
                   border-radius: 0px; margin-top: 14px; padding-top: 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
                   left: 12px; padding: 0 6px;
                   color: {C.ACCENT_PRIMARY}; font-weight: bold; }}

        /* ── Date / Progress / Splitter ── */
        QDateEdit {{ background-color: {C.BG_INPUT}; color: {C.TEXT_MAIN};
                   border: 1px solid {C.BORDER}; border-radius: 0px; padding: 5px; }}
        QDateEdit::drop-down {{ border: none; border-left: 1px solid {C.BORDER};
                   width: 24px; background: transparent; }}
        QProgressBar {{ background-color: {C.BG_INPUT}; border: 1px solid {C.BORDER};
                   border-radius: 0px; text-align: center; color: {C.TEXT_MAIN}; }}
        QProgressBar::chunk {{ background-color: {C.ACCENT_PRIMARY}; }}
        QSplitter::handle {{ background-color: {C.BORDER}; width: 1px; }}

        /* ── Badge trạng thái dạng pill (Bước 2 — cột "Trạng thái") ──
           setProperty("badge", "pass"|"fail"|"run"|"pending") trên QLabel. */
        QLabel[badge="pass"] {{ color: {C.ACCENT_GREEN}; border: 1px solid #1a5a30;
                   background-color: #061408; padding: 2px 10px; font-weight: bold; }}
        QLabel[badge="fail"] {{ color: {C.ACCENT_RED}; border: 1px solid #6a1a10;
                   background-color: #180604; padding: 2px 10px; font-weight: bold; }}
        QLabel[badge="run"] {{ color: {C.ACCENT_PRIMARY}; border: 1px solid #6a5010;
                   background-color: #1e1808; padding: 2px 10px; font-weight: bold; }}
        QLabel[badge="warn"] {{ color: {C.ACCENT_WARN}; border: 1px solid #7a4a10;
                   background-color: #1e1408; padding: 2px 10px; font-weight: bold; }}
        QLabel[badge="pending"] {{ color: {C.TEXT_DIM}; border: 1px solid {C.BORDER};
                   background-color: transparent; padding: 2px 10px; }}

        /* ── Stat card (Bước 2/3 — thẻ tổng hợp số liệu) ── */
        QFrame#stat_card {{ background-color: {C.BG_SURFACE}; border: 1px solid {C.BORDER}; }}
        QFrame#stat_card QLabel[role="stat_label"] {{ color: {C.TEXT_DIM}; font-size: 10px;
                   font-weight: bold; }}
        QFrame#stat_card QLabel[role="stat_val"] {{ font-size: 20px; font-weight: bold; }}

        /* ── Layout-section frames ── */
        QFrame#app_header {{
            background-color: {C.BG_SURFACE};
            border-bottom: 2px solid {C.ACCENT_PRIMARY};
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
