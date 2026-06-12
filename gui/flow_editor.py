"""
gui/flow_editor.py
==================
Màn hình "Flow Editor" — soạn kịch bản kiểu node-flow (như Google Flow).

Bố cục (1600×900):
  - Thanh 3 bước trên cùng (Scan thiết bị → Nhập kịch bản → Xuất kịch bản).
  - Trái  : CONNECTED NODES — thiết bị đã kết nối (từ Step 1).
  - Giữa  : canvas node (kéo-thả, nối dây) trên nền lưới tối.
  - Phải  : NODE PROPERTIES — sửa thuộc tính node đang chọn.

Phiên bản này tập trung tương tác canvas + đồng bộ thuộc tính. Việc map graph
↔ core.scenario.Scenario làm tuyến tính (theo chuỗi nối dây) ở export_scenario().
"""

from __future__ import annotations

import re
import math

from PyQt5.QtCore import Qt, QRectF, QPointF, QLineF, QTimer
from PyQt5.QtGui import (
    QColor, QPen, QBrush, QPainter, QPainterPath, QFont,
)
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QTextEdit, QComboBox, QPushButton, QFrame, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPathItem, QSizePolicy,
)

from gui.theme import Colors
from gui.widgets import ThemeToggle, EXPR_HELP

# Thiết bị mẫu (khi mở độc lập). Khi tích hợp sẽ thay bằng ConnectionProfile.
DEMO_DEVICES = [
    {"name": "Main_Controller_A", "sub": "IP: 192.168.1.105", "icon": "💻", "key": "Main_Controller_A"},
    {"name": "Relay_Module_02",   "sub": "Port: COM3 (9600)", "icon": "🎛", "key": "Relay_Module_02"},
    {"name": "Sensor_Cluster",    "sub": "IP: 192.168.1.200", "icon": "🧮", "key": "Sensor_Cluster"},
]

# Kiểu node: nhãn loại + icon.
NODE_TYPES = {
    "action": ("🟢", "Action Node"),
    "timer":  ("⏳", "Timer Node"),
    "output": ("🚀", "Output Node"),
    "command": ("📡", "Command Node"),
    # biến / tính toán (Phase 5)
    "set_var": ("🔢", "Set Var"),
    "compute": ("🧮", "Compute"),
    "collect": ("📥", "Collect"),
    # marker điều khiển (mở rộng Loop/If thành chuỗi)
    "loop_start": ("🔁", "Loop Start"),
    "loop_end":   ("⏹", "Loop End"),
    "if_start":   ("❓", "If Start"),
    "branch":     ("↳", "Branch"),
    "if_end":     ("⏹", "If End"),
}

# Các kiểu node là MARKER điều khiển (không phải bước thực thi).
MARKER_TYPES = {"loop_start", "loop_end", "if_start", "branch", "if_end"}

NODE_W, NODE_H = 180, 66
PORT_R = 6


# ===========================================================================
# Cạnh nối (dây) giữa cổng ra của node A và cổng vào của node B
# ===========================================================================

class EdgeItem(QGraphicsPathItem):
    def __init__(self, src: "NodeItem", dst: "NodeItem"):
        super().__init__()
        self.src = src
        self.dst = dst
        self.setZValue(-1)
        self.setPen(QPen(QColor(Colors.ACCENT_CYAN), 2))
        src.edges.append(self)
        dst.edges.append(self)
        # Tự thêm vào scene của node nguồn (nếu chưa) để dây HIỂN THỊ.
        sc = src.scene()
        if sc is not None and self.scene() is None:
            sc.addItem(self)
        self.adjust()

    def adjust(self):
        p1 = self.src.output_pos()
        p2 = self.dst.input_pos()
        path = QPainterPath(p1)
        dx = max(40.0, abs(p2.x() - p1.x()) * 0.5)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)


# ===========================================================================
# Node trên canvas
# ===========================================================================

class NodeItem(QGraphicsItem):
    def __init__(self, node_type: str, subtitle: str, ident: str = "",
                 desc: str = "", device: str = "", action: str = "", params: dict | None = None):
        super().__init__()
        self.node_type = node_type if node_type in NODE_TYPES else "command"
        self.subtitle = subtitle
        self.ident = ident
        self.desc = desc
        self.device = device
        self.action = action               # map Scenario: "raw_scpi" | "wait" | ...
        self.params = params or {}         # giữ params gốc để export lại
        self.edges: list[EdgeItem] = []
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

    # --- hình học ---
    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_R, 0, NODE_W + 2 * PORT_R, NODE_H)

    def input_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, NODE_H / 2))

    def output_pos(self) -> QPointF:
        return self.mapToScene(QPointF(NODE_W, NODE_H / 2))

    # --- vẽ ---
    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(0, 0, NODE_W, NODE_H)
        # nền
        p.setBrush(QBrush(QColor(Colors.BG_CARD)))
        border = QColor(Colors.ACCENT_GREEN) if self.isSelected() else QColor(Colors.BORDER)
        p.setPen(QPen(border, 2 if self.isSelected() else 1))
        p.drawRoundedRect(body, 8, 8)

        icon, type_label = NODE_TYPES[self.node_type]
        # dòng loại (nhỏ, mờ)
        p.setPen(QColor(Colors.TEXT_DIM))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(12, 8, NODE_W - 16, 18),
                   Qt.AlignVCenter | Qt.AlignLeft, f"{icon}  {type_label}")
        # dòng tên (đậm, trắng)
        p.setPen(QColor(Colors.TEXT_MAIN))
        f = QFont("Segoe UI", 10); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(12, 28, NODE_W - 16, 28),
                   Qt.AlignVCenter | Qt.AlignLeft, self.subtitle)

        # cổng vào (trái) + ra (phải)
        p.setPen(QPen(QColor(Colors.BORDER), 1))
        p.setBrush(QBrush(QColor(Colors.ACCENT_CYAN)))
        p.drawEllipse(QPointF(0, NODE_H / 2), PORT_R, PORT_R)
        p.drawEllipse(QPointF(NODE_W, NODE_H / 2), PORT_R, PORT_R)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for e in self.edges:
                e.adjust()
        return super().itemChange(change, value)


# ===========================================================================
# Scene + View (canvas)
# ===========================================================================

class FlowScene(QGraphicsScene):
    def __init__(self, on_selection=None):
        super().__init__()
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self._on_selection = on_selection
        self._temp_edge: QGraphicsPathItem | None = None
        self._temp_src: NodeItem | None = None
        self.selectionChanged.connect(self._sel_changed)

    def drawBackground(self, p: QPainter, rect: QRectF):
        p.fillRect(rect, QColor(Colors.BG_INPUT))
        step = 24
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)
        p.setPen(QPen(QColor(Colors.BORDER), 1, Qt.DotLine))
        x = left
        while x < rect.right():
            p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += step

    def _sel_changed(self):
        if self._on_selection:
            sel = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
            self._on_selection(sel[0] if sel else None)

    # --- nối dây ---
    def _port_node_at(self, pos: QPointF, output: bool) -> NodeItem | None:
        for it in self.items(pos):
            if isinstance(it, NodeItem):
                port = it.output_pos() if output else it.input_pos()
                if QLineF(pos, port).length() <= PORT_R + 12:
                    return it
        # quét rộng hơn (vì port nằm ở mép boundingRect)
        for it in self.items():
            if isinstance(it, NodeItem):
                port = it.output_pos() if output else it.input_pos()
                if QLineF(pos, port).length() <= PORT_R + 12:
                    return it
        return None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            src = self._port_node_at(ev.scenePos(), output=True)
            if src is not None:
                self._temp_src = src
                self._temp_edge = QGraphicsPathItem()
                self._temp_edge.setPen(QPen(QColor(Colors.ACCENT_CYAN), 2, Qt.DashLine))
                self._temp_edge.setZValue(-1)
                self.addItem(self._temp_edge)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._temp_edge is not None:
            p1 = self._temp_src.output_pos()
            p2 = ev.scenePos()
            path = QPainterPath(p1)
            dx = max(40.0, abs(p2.x() - p1.x()) * 0.5)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp_edge.setPath(path)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._temp_edge is not None:
            self.removeItem(self._temp_edge)
            dst = self._port_node_at(ev.scenePos(), output=False)
            if dst is not None and dst is not self._temp_src:
                EdgeItem(self._temp_src, dst)
            self._temp_edge = None
            self._temp_src = None
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class FlowView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def wheelEvent(self, ev):
        factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


# ===========================================================================
# Stepper trên cùng
# ===========================================================================

class Stepper(QWidget):
    def __init__(self, steps, current=2, parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = current      # index 0-based; <current = xong (xanh lá)
        self.setFixedHeight(90)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self._steps)
        w = self.width()
        cy = 34
        margin = 90
        gap = (w - 2 * margin) / (n - 1) if n > 1 else 0
        xs = [int(margin + i * gap) for i in range(n)]
        r = 20
        # đường nối
        for i in range(n - 1):
            done = i < self._current
            col = QColor(Colors.ACCENT_GREEN) if done else QColor(Colors.BORDER)
            p.setPen(QPen(col, 4))
            p.drawLine(xs[i] + r, cy, xs[i + 1] - r, cy)
        # vòng tròn + nhãn
        for i, (x, label) in enumerate(zip(xs, self._steps)):
            done = i < self._current
            cur = i == self._current
            if done:
                ring = QColor(Colors.ACCENT_GREEN)
            elif cur:
                ring = QColor(Colors.ACCENT_CYAN)
            else:
                ring = QColor(Colors.BORDER)
            p.setBrush(QBrush(QColor(Colors.BG_WINDOW)))
            p.setPen(QPen(ring, 3))
            p.drawEllipse(QPointF(x, cy), r, r)
            p.setPen(ring)
            f = QFont("Segoe UI", 11); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(x - r, cy - r, 2 * r, 2 * r),
                       Qt.AlignCenter, str(i + 1))
            p.setPen(QColor(Colors.ACCENT_GREEN) if (done or cur) else QColor(Colors.TEXT_DIM))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(x - 90, cy + r + 6, 180, 18), Qt.AlignCenter, label)


# ===========================================================================
# Panel thiết bị (trái)
# ===========================================================================

def _device_card(dev: dict) -> QFrame:
    fr = QFrame()
    fr.setStyleSheet(
        f"QFrame {{ background:{Colors.BG_CARD}; border:1px solid {Colors.BORDER};"
        f" border-radius:8px; }}"
    )
    lay = QHBoxLayout(fr); lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(10)
    icon = QLabel(dev.get("icon", "🔌")); icon.setStyleSheet("font-size:18px; border:none;")
    lay.addWidget(icon)
    col = QVBoxLayout(); col.setSpacing(1)
    name = QLabel(dev["name"]); name.setStyleSheet(
        f"color:{Colors.TEXT_MAIN}; font-weight:bold; border:none;")
    sub = QLabel(dev["sub"]); sub.setStyleSheet(
        f"color:{Colors.TEXT_DIM}; font-size:10px; border:none;")
    col.addWidget(name); col.addWidget(sub); lay.addLayout(col); lay.addStretch()
    dot = QLabel("●"); dot.setStyleSheet(f"color:{Colors.ACCENT_GREEN}; border:none;")
    lay.addWidget(dot)
    return fr


# ===========================================================================
# Cửa sổ chính
# ===========================================================================

class FlowEditorWindow(QMainWindow):
    def __init__(self, devices=None, parent=None, demo=True, on_export=None, on_switch=None):
        super().__init__(parent)
        self.setWindowTitle("FREQ-CAL :: Flow Editor (Theme Digital)")
        self.resize(1600, 900)
        self.devices = devices or DEMO_DEVICES
        self._on_export = on_export          # callback(scn) khi mở từ app; None = lưu .json
        self._on_switch = on_switch          # callback(scn) để quay lại theme Classic
        self._current_node: NodeItem | None = None
        self._build_ui()
        if demo:
            self._load_demo_nodes()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(10, 6, 10, 10); root.setSpacing(8)

        # Hàng trên: stepper + switch chuyển theme ở góc trên phải.
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0); top.setSpacing(8)
        top.addWidget(Stepper(["Scan Thiết Bị", "Nhập Kịch Bản", "Xuất Kịch Bản"], current=2), 1)
        if self._on_switch is not None:
            self.theme_toggle = ThemeToggle(left="Classic", right="Digital", checked=True)
            self.theme_toggle.toggled.connect(
                lambda checked: self._do_switch() if not checked else None)
            holder = QWidget(); hv = QVBoxLayout(holder)
            hv.setContentsMargins(0, 12, 6, 0); hv.addWidget(self.theme_toggle); hv.addStretch()
            top.addWidget(holder, 0)
        root.addLayout(top)

        body = QHBoxLayout(); body.setSpacing(10)
        body.addWidget(self._build_left(), 0)
        body.addWidget(self._build_center(), 1)
        body.addWidget(self._build_right(), 0)
        root.addLayout(body, 1)

    # --- trái ---
    def _build_left(self) -> QWidget:
        panel = QFrame(); panel.setFixedWidth(300)
        panel.setStyleSheet(f"QFrame {{ background:{Colors.BG_WINDOW}; border:none; }}")
        lay = QVBoxLayout(panel); lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("CONNECTED NODES (STEP 1)")
        title.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-weight:bold; font-size:11px;")
        badge = QLabel(f"{len(self.devices)} Nodes")
        badge.setStyleSheet(
            f"color:{Colors.ACCENT_CYAN}; background:{Colors.BG_CARD};"
            f" border:1px solid {Colors.BORDER}; border-radius:9px; padding:2px 8px; font-size:10px;")
        head.addWidget(title); head.addStretch(); head.addWidget(badge)
        lay.addLayout(head)
        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{Colors.BORDER};")
        lay.addWidget(line)
        for dev in self.devices:
            lay.addWidget(_device_card(dev))
        lay.addStretch()
        return panel

    # --- giữa ---
    def _build_center(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)

        # toolbar canvas: thêm/xóa node
        tb = QHBoxLayout(); tb.setSpacing(6)

        def tbtn(text, slot, color=None):
            b = QPushButton(text); b.clicked.connect(slot)
            style = (f"background:{color}; color:{Colors.BG_WINDOW}; font-weight:bold;"
                     if color else f"background:{Colors.BG_CARD}; color:{Colors.TEXT_MAIN};")
            b.setStyleSheet(style + f" border:1px solid {Colors.BORDER}; border-radius:6px; padding:6px 12px;")
            tb.addWidget(b); return b

        tbtn("🟢 + Action", lambda: self.add_node("action", "Bước hành động"))
        tbtn("⏳ + Timer", lambda: self.add_node("timer", "Delay: 1000ms", action="wait",
                                                 params={"seconds": 1.0}))
        tbtn("📡 + Lệnh", lambda: self.add_node("command", "Lệnh mới", action="raw_scpi"))
        tbtn("🧮 + Biến", lambda: self.add_node("compute", "x = 0", action="compute",
                                                params={"name": "x", "expr": "0"}))
        tbtn("🗑 Xóa node", self.delete_selected, Colors.ACCENT_RED)
        tb.addSpacing(12)
        tbtn("↥ Xuất kịch bản", self._do_export, Colors.ACCENT_GREEN)
        tb.addStretch()
        hint = QLabel("Kéo node để di chuyển · kéo từ chấm phải → chấm trái để nối · Delete để xóa")
        hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
        tb.addWidget(hint)
        lay.addLayout(tb)

        self.scene = FlowScene(on_selection=self._on_node_selected)
        self.view = FlowView(self.scene)
        self.view.setStyleSheet(f"border:1px solid {Colors.BORDER}; border-radius:8px;")
        lay.addWidget(self.view, 1)
        return wrap

    # --- phải ---
    def _build_right(self) -> QWidget:
        panel = QFrame(); panel.setFixedWidth(320)
        panel.setStyleSheet(f"QFrame {{ background:{Colors.BG_WINDOW}; border:none; }}")
        lay = QVBoxLayout(panel); lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(6)
        title = QLabel("NODE PROPERTIES")
        title.setStyleSheet(f"color:{Colors.TEXT_MAIN}; font-weight:bold; font-size:13px;")
        lay.addWidget(title)
        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{Colors.BORDER};"); lay.addWidget(line)

        def lbl(t):
            l = QLabel(t); l.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px; font-weight:bold;")
            return l

        lay.addWidget(lbl("TÊN NODE"))
        self.ed_name = QLineEdit()
        self.ed_name.editingFinished.connect(self._on_cmd_text_changed)
        lay.addWidget(self.ed_name)
        lay.addWidget(lbl("MÃ ĐỊNH DANH (ID)"))
        self.ed_id = QLineEdit(); lay.addWidget(self.ed_id)
        lay.addWidget(lbl("MÔ TẢ CHỨC NĂNG"))
        self.ed_desc = QTextEdit(); self.ed_desc.setFixedHeight(70)
        self.ed_desc.setStyleSheet(
            f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_MAIN};"
            f" border:1px solid {Colors.BORDER}; border-radius:4px;")
        lay.addWidget(self.ed_desc)
        lay.addWidget(lbl("GÁN THIẾT BỊ XỬ LÝ (TỪ STEP 1)"))
        self.cb_device = QComboBox()
        self.cb_device.addItem("— (không gán) —", "")
        for dev in self.devices:
            self.cb_device.addItem(dev["name"], dev.get("key", dev["name"]))
        lay.addWidget(self.cb_device)

        # Tham số động cho node Lệnh (placeholder trong lệnh SCPI).
        self.lbl_params = lbl("THAM SỐ LỆNH")
        lay.addWidget(self.lbl_params)
        self.param_host = QWidget()
        self.param_form = QFormLayout(self.param_host)
        self.param_form.setContentsMargins(0, 2, 0, 2)
        self.param_form.setSpacing(5)
        self.param_form.setLabelAlignment(Qt.AlignLeft)
        lay.addWidget(self.param_host)
        self._param_widgets: dict[str, object] = {}

        # Khu BIẾN / TÍNH TOÁN (cho node set_var/compute/collect).
        self.lbl_var = lbl("BIẾN / TÍNH TOÁN")
        lay.addWidget(self.lbl_var)
        self.var_host = QWidget()
        vform = QFormLayout(self.var_host)
        vform.setContentsMargins(0, 2, 0, 2); vform.setSpacing(5)
        self.cb_var_action = QComboBox()
        self.cb_var_action.addItem("Gán biến (set_var)", "set_var")
        self.cb_var_action.addItem("Tính toán (compute)", "compute")
        self.cb_var_action.addItem("Thu thập (collect)", "collect")
        vform.addRow("Thao tác:", self.cb_var_action)
        self.ed_var_name = QLineEdit(); self.ed_var_name.setPlaceholderText("vd: error / samples")
        vform.addRow("Tên biến / list:", self.ed_var_name)
        self.ed_var_expr = QLineEdit()
        self.ed_var_expr.setPlaceholderText("vd: avg(samples) · abs(f_avg-f_set)/f_set · $last")
        self.ed_var_expr.setToolTip(EXPR_HELP)
        vform.addRow("Biểu thức / nguồn:", self.ed_var_expr)
        vhint = QLabel("Hàm: avg, std, min, max, abs, sqrt, count, last · biến $last, $iter")
        vhint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;"); vhint.setWordWrap(True)
        vform.addRow("", vhint)
        lay.addWidget(self.var_host)

        self.btn_save = QPushButton("Lưu cấu hình Node")
        self.btn_save.setStyleSheet(
            f"background:{Colors.ACCENT_CYAN}; color:{Colors.BG_WINDOW}; font-weight:bold;"
            f" border:none; border-radius:6px; padding:10px;")
        self.btn_save.clicked.connect(self._save_node)
        lay.addSpacing(6); lay.addWidget(self.btn_save)
        lay.addStretch()
        self._set_props_enabled(False)
        self._show_var_section(False)
        return panel

    def _set_props_enabled(self, on: bool):
        for w in (self.ed_name, self.ed_id, self.ed_desc, self.cb_device, self.btn_save):
            w.setEnabled(on)

    # --- node demo ---
    def _load_demo_nodes(self):
        a = NodeItem("action", "Start Trigger", "NODE_START_01",
                     "Không tốn thời gian, kích hoạt hệ thống.", "Main_Controller_A")
        a.setPos(-260, 0)
        t = NodeItem("timer", "Delay: 5000ms", "NODE_TIMER_02", "Chờ 5 giây.", "")
        t.setPos(0, 0)
        o = NodeItem("output", "Send Command", "NODE_OUT_03", "Gửi lệnh tới thiết bị.", "Main_Controller_A")
        o.setPos(260, 0)
        for it in (a, t, o):
            self.scene.addItem(it)
        EdgeItem(a, t); EdgeItem(t, o)
        a.setSelected(True)

    def showEvent(self, ev):
        super().showEvent(ev)
        if not getattr(self, "_fitted", False):
            QTimer.singleShot(0, self._fit_all)   # fit khi cửa sổ đã có kích thước
            self._fitted = True

    # --- tham số động (node Lệnh) ---
    def _is_command_node(self, node: "NodeItem | None") -> bool:
        return node is not None and (node.action == "raw_scpi"
                                     or node.node_type in ("command", "output"))

    def _is_var_node(self, node: "NodeItem | None") -> bool:
        return node is not None and node.node_type in ("set_var", "compute", "collect")

    def _show_var_section(self, on: bool):
        self.lbl_var.setVisible(on)
        self.var_host.setVisible(on)

    def _clear_param_form(self):
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self._param_widgets.clear()

    def _refresh_params(self, cmd_text: str, values: dict):
        """Dựng lại các ô nhập tham số từ placeholder trong lệnh SCPI."""
        from core.commands import Cmd, parse_cmd
        self._clear_param_form()
        _, parsed, _ = parse_cmd(Cmd(cmd_text, ""))
        for p in parsed:
            if p.ptype == "enum":
                w = QComboBox()
                for c in p.choices:
                    w.addItem(str(c), c)
                cur = str(values.get(p.name, p.default))
                i = w.findText(cur)
                if i >= 0:
                    w.setCurrentIndex(i)
            else:
                w = QLineEdit(str(values.get(p.name, p.default)))
            label = p.label + (f" ({p.unit})" if p.unit else "")
            self.param_form.addRow(label + ":", w)
            self._param_widgets[p.name] = w
        has = bool(parsed)
        self.lbl_params.setVisible(has)
        self.param_host.setVisible(has)

    def _collect_params(self) -> dict:
        out = {}
        for name, w in self._param_widgets.items():
            if isinstance(w, QComboBox):
                out[name] = w.currentData()
            else:
                out[name] = w.text().strip()
        return out

    def _on_cmd_text_changed(self):
        """Khi sửa TÊN NODE (= lệnh) của node Lệnh -> dựng lại ô tham số."""
        if self._is_command_node(self._current_node):
            merged = dict(self._current_node.params)
            merged.update(self._collect_params())   # giữ giá trị đang gõ
            self._refresh_params(self.ed_name.text(), merged)

    # --- đồng bộ thuộc tính ---
    def _on_node_selected(self, node: NodeItem | None):
        self._current_node = node
        if node is None:
            self._set_props_enabled(False)
            self.ed_name.clear(); self.ed_id.clear(); self.ed_desc.clear()
            self.cb_device.setCurrentIndex(0)
            self._clear_param_form()
            self.lbl_params.setVisible(False); self.param_host.setVisible(False)
            self._show_var_section(False)
            return
        self._set_props_enabled(True)
        self.ed_name.setText(node.subtitle)
        self.ed_id.setText(node.ident)
        self.ed_desc.setPlainText(node.desc)
        idx = self.cb_device.findData(node.device)
        self.cb_device.setCurrentIndex(idx if idx >= 0 else 0)
        # Khu lệnh / khu biến tuỳ loại node.
        is_var = self._is_var_node(node)
        self._show_var_section(is_var)
        if is_var:
            self._clear_param_form()
            self.lbl_params.setVisible(False); self.param_host.setVisible(False)
            self.cb_var_action.setCurrentIndex(max(0, self.cb_var_action.findData(node.node_type)))
            if node.node_type == "collect":
                self.ed_var_name.setText(node.params.get("var", ""))
                self.ed_var_expr.setText(node.params.get("source", "$last"))
            else:
                self.ed_var_name.setText(node.params.get("name") or node.params.get("target", ""))
                self.ed_var_expr.setText(node.params.get("expr", ""))
        elif self._is_command_node(node):
            self._refresh_params(node.subtitle, node.params)
        else:
            self._clear_param_form()
            self.lbl_params.setVisible(False); self.param_host.setVisible(False)

    def _save_node(self):
        if self._current_node is None:
            return
        n = self._current_node
        n.ident = self.ed_id.text().strip()
        n.desc = self.ed_desc.toPlainText().strip()
        if self._is_var_node(n):
            # Node biến: dựng params + subtitle từ khu BIẾN.
            act = self.cb_var_action.currentData()
            name = self.ed_var_name.text().strip()
            expr = self.ed_var_expr.text().strip()
            n.node_type = act; n.action = act
            if act == "collect":
                n.params = {"var": name, "source": expr or "$last"}
                n.subtitle = f"{name} ← {expr or '$last'}"
            else:
                n.params = {"name": name, "expr": expr}
                n.subtitle = f"{name} = {expr}"
            n.update()
            return
        n.subtitle = self.ed_name.text().strip() or n.subtitle
        n.device = self.cb_device.currentData()
        if self._is_command_node(n):
            # Dựng lại params đầy đủ từ lệnh (tên node) + giá trị tham số nhập tay.
            from core.commands import Cmd, parse_cmd
            template, parsed, is_query = parse_cmd(Cmd(n.subtitle, n.desc))
            params = {"__template__": template, "__is_query__": is_query,
                      "__cmd_original__": n.subtitle, "__cmd_desc__": n.desc}
            vals = self._collect_params()
            for p in parsed:
                params[p.name] = vals.get(p.name, p.default)
            n.params = params
        n.update()

    # --- thêm / xóa node ---
    def add_node(self, node_type, subtitle, action="", params=None) -> NodeItem:
        # Nối chuỗi vào node ĐANG CHỌN; nếu không có thì nối tiếp node thêm gần nhất.
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        prev = sel[0] if sel else getattr(self, "_last_added", None)
        prev_ok = prev is not None and prev.scene() is self.scene
        n = NodeItem(node_type, subtitle, action=action, params=params)
        if prev_ok:                        # đặt ngay bên phải node trước
            n.setPos(prev.pos().x() + 240, prev.pos().y())
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            n.setPos(center.x() - NODE_W / 2, center.y() - NODE_H / 2)
        self.scene.addItem(n)
        if prev_ok:
            EdgeItem(prev, n)              # TỰ NỐI từ node trước -> node mới
        self.scene.clearSelection()
        n.setSelected(True)
        self._last_added = n
        self._update_scene_rect()          # mở rộng vùng cuộn nếu node ra ngoài
        return n

    def delete_selected(self):
        for it in list(self.scene.selectedItems()):
            if not isinstance(it, NodeItem):
                continue
            for e in list(it.edges):
                other = e.dst if e.src is it else e.src
                if e in other.edges:
                    other.edges.remove(e)
                if e.scene():
                    self.scene.removeItem(e)
            self.scene.removeItem(it)
        self._on_node_selected(None)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
        else:
            super().keyPressEvent(ev)

    # --- nạp Scenario hiện có thành chuỗi node (mở rộng Loop/If) ---
    def load_scenario(self, scn):
        self.scene.clear()
        self._current_node = None
        seq: list[NodeItem] = []
        for node in getattr(scn, "nodes", []):
            seq.extend(self._nodes_for(node))
        # Bố trí dạng LƯỚI RẮN (snake) — xuống hàng thay vì 1 hàng ngang vô tận;
        # node liên tiếp luôn cạnh nhau (hàng lẻ đảo chiều) nên dây nối gọn.
        n = len(seq)
        per_row = max(1, min(8, math.ceil(math.sqrt(n)))) if n else 1
        col_w, row_h = 240, 130
        prev = None
        for i, ni in enumerate(seq):
            r, c = divmod(i, per_row)
            if r % 2 == 1:
                c = per_row - 1 - c          # hàng lẻ đi ngược -> nối liền mạch
            ni.setPos(c * col_w, r * row_h)
            self.scene.addItem(ni)
            if prev is not None:
                EdgeItem(prev, ni)
            prev = ni
        self._update_scene_rect()
        QTimer.singleShot(0, self._fit_all)   # fit sau khi view đã có kích thước
        self._on_node_selected(None)

    def _update_scene_rect(self):
        """Mở rộng vùng cuộn ôm hết node (+lề) để kéo tới mọi node."""
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            self.scene.setSceneRect(-1000, -1000, 2000, 2000)
        else:
            self.scene.setSceneRect(rect.adjusted(-400, -400, 400, 400))

    def _fit_all(self):
        """Thu phóng để THẤY HẾT các node trong vùng hiển thị (không phóng quá 1:1)."""
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.view.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        if self.view.transform().m11() > 1.0:    # ít node -> đừng phóng to
            self.view.resetTransform()
            self.view.centerOn(rect.center())

    def _node_from_step(self, step) -> NodeItem:
        if step.action == "raw_scpi":
            sub = step.params.get("__cmd_original__",
                                  step.params.get("__template__", "lệnh"))
            return NodeItem("command", sub, desc=step.params.get("__cmd_desc__", ""),
                            device=(step.devices[0] if step.devices else ""),
                            action="raw_scpi", params=dict(step.params))
        if step.action == "wait":
            s = step.params.get("seconds", 0)
            return NodeItem("timer", f"Delay: {s}s", action="wait", params=dict(step.params))
        if step.action in ("set_var", "compute"):
            name = step.params.get("name") or step.params.get("target", "")
            return NodeItem(step.action, f"{name} = {step.params.get('expr', '')}",
                            action=step.action, params=dict(step.params))
        if step.action == "collect":
            return NodeItem("collect",
                            f"{step.params.get('var', '')} ← {step.params.get('source', '$last')}",
                            action="collect", params=dict(step.params))
        return NodeItem("action", step.action, action=step.action, params=dict(step.params))

    def _nodes_for(self, node) -> list[NodeItem]:
        """Một node Scenario -> danh sách NodeItem. Container (Loop/If) mở rộng
        start/body/end; body ĐỆ QUY nên Loop/If LỒNG NHAU vẫn dựng được."""
        from core.scenario import ScenarioStep, LoopBlock, IfBlock
        if isinstance(node, ScenarioStep):
            return [self._node_from_step(node)]
        if isinstance(node, LoopBlock):
            if getattr(node, "mode", "count") == "until":
                sub = f"Đến khi: {node.condition.describe() if node.condition else '?'}"
            else:
                sub = f"Lặp {node.count} lần"
            start = NodeItem("loop_start", sub, params={
                "mode": getattr(node, "mode", "count"), "count": node.count,
                "max_iter": getattr(node, "max_iter", 50),
                "__condition__": getattr(node, "condition", None)})
            out = [start]
            for child in node.body:
                out += self._nodes_for(child)            # đệ quy -> lồng
            out.append(NodeItem("loop_end", "Kết thúc lặp"))
            return out
        if isinstance(node, IfBlock):
            out = [NodeItem("if_start", "Rẽ nhánh (If)")]
            for i, br in enumerate(node.branches):
                if br.condition is None:
                    blbl = "Ngược lại (ELSE)"
                else:
                    blbl = ("Nếu " if i == 0 else "Ngược lại nếu ") + br.condition.describe()
                out.append(NodeItem("branch", blbl, params={"__condition__": br.condition}))
                for child in br.body:
                    out += self._nodes_for(child)        # đệ quy -> lồng
            out.append(NodeItem("if_end", "Kết thúc rẽ nhánh"))
            return out
        return [NodeItem("action", "Node")]

    # --- export ngược: node graph -> Scenario ---
    def _ordered_nodes(self) -> list[NodeItem]:
        """Sắp xếp node theo CHUỖI NỐI DÂY: bắt đầu từ node không có dây vào, đi
        theo dây ra; node rời rạc xếp theo toạ độ x."""
        nodes = [it for it in self.scene.items() if isinstance(it, NodeItem)]
        indeg = {n: 0 for n in nodes}
        nxt: dict[NodeItem, NodeItem] = {}
        for n in nodes:
            for e in n.edges:
                if e.src is n:
                    indeg[e.dst] = indeg.get(e.dst, 0) + 1
                    nxt.setdefault(n, e.dst)
        order, seen = [], set()
        starts = sorted([n for n in nodes if indeg[n] == 0],
                        key=lambda n: n.scenePos().x())
        for s in starts:
            cur = s
            while cur is not None and cur not in seen:
                order.append(cur); seen.add(cur)
                cur = nxt.get(cur)
        for n in sorted(nodes, key=lambda n: n.scenePos().x()):
            if n not in seen:
                order.append(n); seen.add(n)
        return order

    def _scenario_from_node(self, n: NodeItem):
        from core.scenario import ScenarioStep
        from core.commands import Cmd, parse_cmd
        if n.node_type in MARKER_TYPES:               # marker điều khiển -> không là bước
            return None
        # Node Biến / Tính toán -> giữ nguyên action + params
        if n.action in ("set_var", "compute", "collect"):
            return ScenarioStep(action=n.action, devices=[], params=dict(n.params))
        # Node Lệnh -> raw_scpi
        if n.action == "raw_scpi" or n.node_type in ("command", "output"):
            if n.params.get("__template__"):          # node nạp từ kịch bản: giữ params gốc
                params = dict(n.params)
            else:                                     # node tạo tay: tên node = lệnh SCPI
                template, parsed, is_query = parse_cmd(Cmd(n.subtitle, n.desc))
                params = {"__template__": template, "__is_query__": is_query,
                          "__cmd_original__": n.subtitle, "__cmd_desc__": n.desc}
                for p in parsed:
                    params[p.name] = p.default
            devices = [n.device] if n.device else []
            return ScenarioStep(action="raw_scpi", devices=devices,
                                params=params, note=n.desc)
        # Node Timer -> wait (đọc số giây từ tên 'Delay: Xms/Xs' nếu có)
        if n.action == "wait" or n.node_type == "timer":
            seconds = float(n.params.get("seconds", 0) or 0)
            m = re.search(r"([\d.]+)\s*(ms|s)?", n.subtitle)
            if m:
                v = float(m.group(1))
                seconds = v / 1000.0 if m.group(2) == "ms" else v
            return ScenarioStep(action="wait", devices=[], params={"seconds": seconds})
        # Action có sẵn khác (identify, set_frequency…) -> giữ nguyên
        if n.action and n.action != "action":
            return ScenarioStep(action=n.action,
                                devices=[n.device] if n.device else [],
                                params=dict(n.params), note=n.desc)
        return None      # node 'Action'/marker -> không xuất

    def export_scenario(self):
        """Dựng Scenario từ chuỗi node bằng STACK -> tái tạo Loop/If LỒNG NHAU
        và Loop-until (giữ mode/điều kiện/max_iter)."""
        from core.scenario import Scenario, LoopBlock, IfBlock, Branch
        root: list = []
        stack = [{"kind": "root", "list": root}]

        def add(item):
            fr = stack[-1]
            if fr["kind"] == "root":
                fr["list"].append(item)
            elif fr["kind"] == "loop":
                fr["body"].append(item)
            elif fr["kind"] == "if" and fr["cur"] is not None:
                fr["cur"].body.append(item)

        def close_loop(fr):
            p = fr["node"].params
            add(LoopBlock(count=int(p.get("count", 2) or 2), body=fr["body"],
                          mode=p.get("mode", "count"),
                          condition=p.get("__condition__"),
                          max_iter=int(p.get("max_iter", 50) or 50)))

        for n in self._ordered_nodes():
            t = n.node_type
            if t == "loop_start":
                stack.append({"kind": "loop", "body": [], "node": n})
            elif t == "loop_end":
                if stack[-1]["kind"] == "loop":
                    close_loop(stack.pop())
            elif t == "if_start":
                stack.append({"kind": "if", "branches": [], "cur": None})
            elif t == "branch":
                if stack[-1]["kind"] == "if":
                    br = Branch(condition=n.params.get("__condition__"), body=[])
                    stack[-1]["branches"].append(br)
                    stack[-1]["cur"] = br
            elif t == "if_end":
                if stack[-1]["kind"] == "if":
                    fr = stack.pop()
                    add(IfBlock(branches=fr["branches"]))
            else:
                step = self._scenario_from_node(n)
                if step is not None:
                    add(step)
        # đóng các frame còn dở (marker thiếu end) — best effort
        while len(stack) > 1:
            fr = stack.pop()
            if fr["kind"] == "loop":
                close_loop(fr)
            elif fr["kind"] == "if":
                add(IfBlock(branches=fr["branches"]))
        scn = Scenario(name="Sơ đồ luồng")
        scn.nodes = root
        return scn

    def _do_export(self):
        from PyQt5.QtWidgets import QMessageBox, QFileDialog
        scn = self.export_scenario()
        if not scn.nodes:
            QMessageBox.warning(self, "Trống", "Chưa có node nào xuất được thành bước.")
            return
        if self._on_export is not None:          # mở từ app -> đẩy về grid
            self._on_export(scn)
            QMessageBox.information(self, "Đã xuất",
                                   f"Đã nhập {len(scn.nodes)} mục vào Scenario Builder.")
        else:                                    # độc lập -> lưu .json
            path, _ = QFileDialog.getSaveFileName(self, "Lưu kịch bản", "scenario.json",
                                                  "JSON (*.json)")
            if path:
                scn.save_json(path)
                QMessageBox.information(self, "Đã lưu", f"Đã lưu {len(scn.nodes)} mục:\n{path}")

    def _do_switch(self):
        """Chuyển về theme Classic, mang theo kịch bản đang dựng."""
        if self._on_switch is not None:
            self._switched = True
            self._on_switch(self.export_scenario())
            self.close()

    def closeEvent(self, ev):
        # Đóng cửa sổ Digital (X) -> quay lại Classic, KHÔNG đổi kịch bản. Dùng
        # callback (cửa sổ top-level, không còn parent()).
        if self._on_switch is not None and not getattr(self, "_switched", False):
            self._on_switch(None)
        super().closeEvent(ev)


def run_flow_editor(devices=None):
    """Mở Flow Editor. Chạy độc lập (tạo QApplication + exec_) hoặc mở từ trong
    app đang chạy (chỉ show, không tạo vòng lặp lồng)."""
    import sys
    from PyQt5.QtWidgets import QApplication
    from gui.theme import build_global_qss
    existing = QApplication.instance()
    app = existing or QApplication(sys.argv)
    if existing is None:
        app.setStyleSheet(build_global_qss())
    win = FlowEditorWindow(devices=devices)
    win.show()
    if existing is None:
        app.exec_()
    return win


if __name__ == "__main__":
    run_flow_editor()
