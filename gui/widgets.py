"""
gui/widgets.py
==============
Widget dùng chung. ThemeToggle: nút on/off dạng segmented (Classic ⇄ Digital)
đặt ở góc trên phải để chuyển layout.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QRect, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont
from PyQt5.QtWidgets import QWidget, QHeaderView, QStyle, QStyleOptionButton, QLabel

from gui.theme import Colors


# ============================================================================
# Badge trạng thái dạng pill — QLabel[badge="pass|fail|run|warn|pending"]
# (style thật khai trong gui/theme.py::build_global_qss). Dùng chung cho cột
# Trạng thái ở Bước 2 (session_manager.py) và cây Scenario Builder
# (scenario_grid.py) — tránh mỗi nơi tự suy diễn 1 kiểu map màu->badge riêng.
# ============================================================================

_BADGE_KIND_BY_COLOR = {
    Colors.ACCENT_GREEN:   "pass",
    Colors.ACCENT_RED:     "fail",
    Colors.ACCENT_PRIMARY: "run",
    Colors.ACCENT_WARN:    "warn",
}


def badge_kind_for_color(color: str) -> str:
    return _BADGE_KIND_BY_COLOR.get(color, "pending")


def set_badge(label: QLabel, text: str, color: str):
    """Cập nhật 1 QLabel[badge=...] hiện có — đổi property "badge" rồi bắt Qt
    tính lại style (Qt không tự re-polish khi 1 dynamic property QSS đang
    dựa vào bị đổi giá trị sau khi widget đã hiển thị)."""
    label.setText(text)
    kind = badge_kind_for_color(color)
    label.setProperty("badge", kind)
    label.style().unpolish(label)
    label.style().polish(label)


# ============================================================================
# Viền góc trang trí (corner bracket) — mô phỏng .corner.tl/tr/bl/br của
# mockup HUD mà không cần frameless window: vẽ đè lên nội dung, dùng trong
# paintEvent() của dialog: super().paintEvent(ev); paint_corner_brackets(self).
# ============================================================================

def paint_corner_brackets(widget: QWidget, length: int = 10,
                          color: str = Colors.ACCENT_PRIMARY,
                          corners: str = "tl,tr,bl,br"):
    p = QPainter(widget)
    p.setPen(QPen(QColor(color), 1))
    w, h = widget.width(), widget.height()
    wanted = set(corners.split(","))
    if "tl" in wanted:
        p.drawLine(0, 0, length, 0); p.drawLine(0, 0, 0, length)
    if "tr" in wanted:
        p.drawLine(w - 1 - length, 0, w - 1, 0); p.drawLine(w - 1, 0, w - 1, length)
    if "bl" in wanted:
        p.drawLine(0, h - 1 - length, 0, h - 1); p.drawLine(0, h - 1, length, h - 1)
    if "br" in wanted:
        p.drawLine(w - 1 - length, h - 1, w - 1, h - 1); p.drawLine(w - 1, h - 1 - length, w - 1, h - 1)
    p.end()


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


class CheckBoxHeader(QHeaderView):
    """Header ngang có ô tick ở cột 0 để chọn/bỏ chọn TẤT CẢ dòng cùng lúc —
    dùng cho cột "Chạy" (Bước 2) và cột "Đưa vào báo cáo" (bảng kết quả
    WYSIWYG) — cả 2 đều đặt cột checkbox ở vị trí 0."""
    toggled_all = pyqtSignal(bool)

    def __init__(self, parent=None, label="Bật"):
        super().__init__(Qt.Horizontal, parent)
        self._checked = False
        self._label = label
        self.setSectionsClickable(True)

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.updateSection(0)

    def paintSection(self, painter, rect, logicalIndex):
        # Cột 1+ do QSS vẽ (đã có border-bottom + border-right). Chỉ cột 0 vẽ tay
        # để chèn ô tick — nên tự vẽ luôn đường ngang dưới + dọc phải cho đồng bộ.
        if logicalIndex != 0:
            super().paintSection(painter, rect, logicalIndex)
            return
        painter.save()
        painter.fillRect(rect, QColor(Colors.BG_CARD))
        painter.setPen(QColor(Colors.BORDER))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())   # ngang dưới
        painter.drawLine(rect.topRight(), rect.bottomRight())     # dọc phải (ngăn cách cột)
        sz = 15
        cb = QRect(rect.x() + 6, rect.y() + (rect.height() - sz) // 2, sz, sz)
        opt = QStyleOptionButton()
        opt.rect = cb
        opt.state = QStyle.State_Enabled | (QStyle.State_On if self._checked else QStyle.State_Off)
        self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, painter)
        painter.setPen(QColor(Colors.TEXT_DIM))
        text_rect = QRect(cb.right() + 6, rect.y(),
                          rect.width() - (cb.right() + 6 - rect.x()), rect.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._label)
        painter.restore()

    def _checkbox_rect(self) -> QRect:
        """Vùng hình ô tick ở cột 0 (toạ độ viewport của header)."""
        sz = 15
        x0 = self.sectionViewportPosition(0)
        return QRect(x0 + 6, (self.height() - sz) // 2, sz, sz)

    def mousePressEvent(self, event):
        # Chỉ bật/tắt "chọn tất cả" khi bấm ĐÚNG vào ô tick. Mọi chỗ khác — kể cả
        # mép giữa các cột để KÉO RỘNG/HẸP — đều để QHeaderView xử lý như thường.
        if self._checkbox_rect().contains(event.pos()):
            self.setChecked(not self._checked)
            self.toggled_all.emit(self._checked)
            return
        super().mousePressEvent(event)


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
        p.setBrush(QColor(Colors.ACCENT_PRIMARY))
        p.drawRoundedRect(QRectF(ax, r.top(), hw, r.height()), rad, rad)
        # nhãn
        p.setFont(QFont("Consolas", 9, QFont.Bold))
        lrect = QRectF(r.left(), r.top(), hw, r.height())
        rrect = QRectF(r.left() + hw, r.top(), hw, r.height())
        p.setPen(QColor(Colors.BG_WINDOW if not self._checked else Colors.TEXT_DIM))
        p.drawText(lrect, Qt.AlignCenter, self._left)
        p.setPen(QColor(Colors.BG_WINDOW if self._checked else Colors.TEXT_DIM))
        p.drawText(rrect, Qt.AlignCenter, self._right)
