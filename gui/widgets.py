"""
gui/widgets.py
==============
Widget dùng chung. ThemeToggle: nút on/off dạng segmented (Classic ⇄ Digital)
đặt ở góc trên phải để chuyển layout.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from PyQt5.QtWidgets import QWidget

from gui.theme import Colors


# Tooltip mô tả cú pháp biểu thức (dùng cho ô Biểu thức/nguồn ở Classic & Digital).
EXPR_HELP = (
    "<b>Biểu thức</b> (set_var/compute) hoặc <b>nguồn</b> (collect).<br><br>"
    "<b>Biến đặc biệt</b><br>"
    "• <code>$last</code> — giá trị ĐO gần nhất (từ lệnh query/đo trước đó)<br>"
    "• <code>$iter</code> — chỉ số VÒNG LẶP hiện tại (1, 2, 3…)<br>"
    "• <i>tên_biến</i> — biến đã tạo bằng set_var/compute/collect<br><br>"
    "<b>Hàm</b><br>"
    "• <code>avg(xs)</code> / <code>mean(xs)</code> — trung bình<br>"
    "• <code>std(xs)</code> — độ lệch chuẩn · <code>count(xs)</code> — số phần tử<br>"
    "• <code>min(xs)</code> <code>max(xs)</code> <code>last(xs)</code><br>"
    "• <code>abs(x)</code> <code>sqrt(x)</code><br>"
    "&nbsp;&nbsp;(nhận 1 list: <code>avg(samples)</code> — hoặc nhiều số: <code>avg(1,2,3)</code>)<br><br>"
    "<b>Toán tử</b>: + − * / % **  và ngoặc ( )<br>"
    "<b>List</b>: <code>[]</code> (rỗng), <code>[1,2,3]</code><br><br>"
    "<b>Ví dụ (đo độ nhạy)</b><br>"
    "• <code>samples = []</code>  → khởi tạo list<br>"
    "• collect, nguồn = <code>$last</code>  → gom mỗi lần đo<br>"
    "• <code>f_avg = avg(samples)</code><br>"
    "• <code>error = abs(f_avg - f_set) / f_set</code><br>"
    "• <code>pw = p_base + 0.5*($iter-1)</code>  → tăng theo vòng"
)


class ThemeToggle(QWidget):
    """Switch 2 trạng thái: trái (False) ↔ phải (True), kèm nhãn."""
    toggled = pyqtSignal(bool)

    def __init__(self, left="Classic", right="Digital", checked=False, parent=None):
        super().__init__(parent)
        self._left, self._right = left, right
        self._checked = bool(checked)
        self.setFixedSize(200, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Chuyển giao diện Classic ⇄ Digital")

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool, emit: bool = True):
        v = bool(v)
        if v != self._checked:
            self._checked = v
            self.update()
            if emit:
                self.toggled.emit(v)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = r.height() / 2
        # track
        p.setPen(QPen(QColor(Colors.BORDER), 1))
        p.setBrush(QColor(Colors.BG_CARD))
        p.drawRoundedRect(r, rad, rad)
        # nửa đang chọn (highlight)
        hw = r.width() / 2
        ax = r.left() + (hw if self._checked else 0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(Colors.ACCENT_CYAN))
        p.drawRoundedRect(QRectF(ax, r.top(), hw, r.height()), rad, rad)
        # nhãn
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lrect = QRectF(r.left(), r.top(), hw, r.height())
        rrect = QRectF(r.left() + hw, r.top(), hw, r.height())
        p.setPen(QColor(Colors.BG_WINDOW if not self._checked else Colors.TEXT_DIM))
        p.drawText(lrect, Qt.AlignCenter, self._left)
        p.setPen(QColor(Colors.BG_WINDOW if self._checked else Colors.TEXT_DIM))
        p.drawText(rrect, Qt.AlignCenter, self._right)
