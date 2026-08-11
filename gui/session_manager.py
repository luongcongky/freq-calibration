"""
gui/session_manager.py
======================
Màn hình chính "Phiên Kiểm Định" — quản lý một phiên kiểm định hoàn chỉnh,
trình bày dạng wizard 3 bước (cột trái: step rail, cột phải: nội dung bước):
  Bước 1: Thông tin phiên (DUT + metadata)
  Bước 2: Danh sách bài đo (chạy test, rà soát & xác nhận từng dòng kết quả)
  Bước 3: Xuất báo cáo (xem trước nội dung đã xác nhận, xuất & mở file)

SessionManagerWindow là QMainWindow — điểm vào chính của ứng dụng.
Scenario Builder mở như cửa sổ phụ từ đây.
"""

from __future__ import annotations

import os
import logging
from datetime import date, datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLabel, QLineEdit, QFormLayout, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QDateEdit, QProgressBar, QSplitter,
    QListWidget, QAbstractItemView, QCheckBox,
    QGroupBox, QScrollArea, QApplication, QFrame, QStackedWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt5.QtGui import QColor, QIcon, QPixmap

from core.session import CalibrationSession, SessionMeta, DUTInfo, SessionTest
from core.scenario import Scenario
from core.scenario_runner import ScenarioRunner, StepResult
from core.report_templates import list_templates, get_template
from core import table_engine
from gui.theme import Colors, build_global_qss
from gui.report_preview import build_wysiwyg_table
from gui.widgets import CheckBoxHeader, set_badge

logger = logging.getLogger(__name__)

# ============================================================================
# Hằng số
# ============================================================================

STATUS_LABELS = {
    "pending":  ("⏳ Chờ",       Colors.TEXT_DIM),
    "running":  ("▶ Đang chạy",  Colors.ACCENT_PRIMARY),
    "failed":   ("❌ Lỗi",       Colors.ACCENT_RED),
    "skipped":  ("— Bỏ qua",    Colors.TEXT_DIM),
}

_COL_CHK    = 0
_COL_TBL    = 1
_COL_NAME   = 2
_COL_FILE   = 3
_COL_STATUS = 4
TEST_COLS = ["Chạy", "Bảng", "Tên bài test", "File kịch bản (.json)", "Trạng thái"]


def _test_status_label(test: SessionTest) -> tuple[str, str]:
    """Nhãn + màu cho cột Trạng thái — bài 'done' hiển thị tiến độ xác nhận
    theo từng dòng kết quả thay vì chỉ 'Xong'."""
    if not test.enabled:
        return "— Bỏ qua", Colors.TEXT_DIM
    if test.status == "done":
        rows = test.result_table.rows if test.result_table else []
        n = len(rows)
        c = sum(1 for r in rows if r.confirmed)
        if n == 0:
            return "✅ Xong", Colors.ACCENT_GREEN
        if c == 0:
            return f"🟡 Chờ xác nhận (0/{n})", Colors.ACCENT_WARN
        if c == n:
            return f"✅ Đã xác nhận ({c}/{n})", Colors.ACCENT_GREEN
        return f"🔶 Đã xác nhận ({c}/{n})", Colors.ACCENT_WARN
    return STATUS_LABELS.get(test.status, (test.status, Colors.TEXT_DIM))


# _set_badge/_badge_kind_for_color -> gui/widgets.py (dùng chung với
# scenario_grid.py). Giữ alias nội bộ ngắn gọn cho code bên dưới.
_set_badge = set_badge


def _scaffold_rows(template_id: str, test: SessionTest) -> list:
    """Bài chưa chạy (result_table=None) -> dựng khung bảng theo đúng mẫu
    báo cáo (đủ số dòng, giá trị để trống) để xem trước cấu trúc đo, dùng
    chung cho Bước 2 (_TestReviewTab) và Bước 3 (_ExportTab)."""
    if not template_id:
        return []
    try:
        tpl = get_template(template_id)
        rt = tpl.map_test_result(test)
    except Exception:  # noqa: BLE001
        return []
    return rt.rows if rt else []


def _make_recompute_row(template_id: str, table_id: str):
    """Trả callback recompute_row(row_index, raw_readings) cho
    build_wysiwyg_table() — dùng đúng công thức pass_rule của descriptor
    thật (core/table_engine.py::recompute_row) khi kiểm định viên sửa tay
    1 giá trị đo ở Bước 2/Bước 3. None nếu template/bảng không tồn tại (vd
    lỗi cấu hình) -> _build_generic tự khoá double-click, không lỗi."""
    def _recompute(row_index: int, raw_readings: list):
        try:
            tpl = get_template(template_id)
            descriptor_for = getattr(tpl, "descriptor_for", None)
            descriptor = descriptor_for(table_id) if descriptor_for else None
        except Exception:  # noqa: BLE001
            return None
        if descriptor is None:
            return None
        return table_engine.recompute_row(descriptor, row_index, raw_readings)
    return _recompute


def _measured_counts_for(template_id: str, table_id: str, n_rows: int):
    """[row_def.measured_count, ...] khớp đúng thứ tự rows đang hiển thị —
    cho _build_generic biết những report_val() nào là lần đo thật, những
    report_val() nào là field kịch bản TỰ TÍNH đẩy thêm (vd A1/A5-A8 QTKĐ
    2.461), để đặt tên cột 'KB tính N' thay vì 'Lần N' cho đúng bản chất
    (không phải khớp cấu trúc docx thật — panel Bước 2 vốn không đọc file
    docx, chỉ là bảng rà soát chung, xem gui/report_preview.py). None nếu
    template/bảng không tồn tại."""
    try:
        tpl = get_template(template_id)
        descriptor_for = getattr(tpl, "descriptor_for", None)
        descriptor = descriptor_for(table_id) if descriptor_for else None
    except Exception:  # noqa: BLE001
        return None
    if descriptor is None:
        return None
    return [rd.measured_count for rd in descriptor.rows[:n_rows]]


# ============================================================================
# Worker: chạy 1 scenario trong nền
# ============================================================================

class _TestWorker(QThread):
    result_ready = pyqtSignal(object)
    finished_all = pyqtSignal(int)
    failed       = pyqtSignal(str)

    def __init__(self, scenario: Scenario, address_map: dict, cmd_delay_s: float):
        super().__init__()
        self._scn = scenario
        self._addr = address_map
        self._delay = cmd_delay_s
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            runner = ScenarioRunner(
                mock=False,
                address_map=self._addr,
                on_result=self.result_ready.emit,
                stop_flag=lambda: self._stop,
                cmd_delay_s=self._delay,
            )
            results = runner.run(self._scn)
            self.finished_all.emit(len(results))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Test worker failed")
            self.failed.emit(str(exc))


# ============================================================================
# Step rail — cột trái kiểu wizard dọc (chấm tròn + đường nối)
# ============================================================================

class _StepRail(QWidget):
    step_clicked = pyqtSignal(int)

    def __init__(self, steps: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("step_rail")
        self.setStyleSheet(
            f"QWidget#step_rail {{ background-color:{Colors.BG_SURFACE}; "
            f"border-right:1px solid {Colors.BORDER}; }}"
        )
        self._current = 0
        self._rows: list[QWidget] = []
        self._dots: list[QLabel] = []
        self._titles: list[QLabel] = []
        self._subtitles: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 20)
        layout.setSpacing(0)

        for i, (title, subtitle) in enumerate(steps):
            row = QFrame()
            row.setCursor(Qt.PointingHandCursor)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(16, 12, 16, 12)
            row_lay.setSpacing(10)

            dot_col = QVBoxLayout()
            dot_col.setSpacing(0)
            dot_col.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("○")
            dot.setFixedWidth(22)
            dot.setAlignment(Qt.AlignCenter)
            dot_col.addWidget(dot, alignment=Qt.AlignHCenter)
            if i < len(steps) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.VLine)
                line.setFixedWidth(2)
                line.setMinimumHeight(30)
                line.setStyleSheet(f"background-color:{Colors.BORDER}; border:none;")
                dot_col.addWidget(line, alignment=Qt.AlignHCenter)
            row_lay.addLayout(dot_col)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            t_lbl = QLabel(title.upper())
            t_lbl.setWordWrap(True)
            s_lbl = QLabel(subtitle)
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px; background:transparent;")
            text_col.addWidget(t_lbl)
            text_col.addWidget(s_lbl)
            row_lay.addLayout(text_col, 1)

            row.mousePressEvent = lambda _ev, idx=i: self.step_clicked.emit(idx)
            layout.addWidget(row)

            self._rows.append(row)
            self._dots.append(dot)
            self._titles.append(t_lbl)
            self._subtitles.append(s_lbl)

        layout.addStretch()

        # -- Biểu mẫu đang dùng (footer) --
        footer = QFrame()
        footer.setStyleSheet(f"QFrame {{ border:none; border-top:1px solid {Colors.BORDER}; }}")
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(16, 14, 16, 14)
        footer_lay.setSpacing(4)
        footer_cap = QLabel("BIỂU MẪU ĐANG DÙNG")
        footer_cap.setStyleSheet(f"color:{Colors.BORDER}; font-size:9px; font-weight:bold; background:transparent;")
        footer_lay.addWidget(footer_cap)
        self._lbl_tpl_standard = QLabel("— Chưa chọn mẫu —")
        self._lbl_tpl_standard.setWordWrap(True)
        self._lbl_tpl_standard.setStyleSheet(
            f"color:{Colors.TEXT_MAIN}; font-size:12px; font-weight:bold; background:transparent;")
        footer_lay.addWidget(self._lbl_tpl_standard)
        self._lbl_tpl_name = QLabel("")
        self._lbl_tpl_name.setWordWrap(True)
        self._lbl_tpl_name.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px; background:transparent;")
        footer_lay.addWidget(self._lbl_tpl_name)
        layout.addWidget(footer)

        self.set_current(0)

    def set_template_info(self, standard: str, name: str):
        """Cập nhật footer 'Biểu mẫu đang dùng' — gọi mỗi khi mẫu báo cáo
        đang dùng của phiên đổi (chọn mẫu, mở phiên đã lưu, tạo phiên mới)."""
        self._lbl_tpl_standard.setText(standard or "— Chưa chọn mẫu —")
        self._lbl_tpl_name.setText(name or "")

    def set_current(self, index: int):
        self._current = index
        for i, (row, dot, title, sub) in enumerate(zip(self._rows, self._dots, self._titles, self._subtitles)):
            if i < index:
                dot.setText("✓")
                dot.setStyleSheet(f"font-size:14px; font-weight:bold; color:{Colors.ACCENT_GREEN}; background:transparent;")
                title.setStyleSheet(f"color:{Colors.ACCENT_GREEN}; font-size:13px; font-weight:bold; "
                                    f"background:transparent;")
                sub.setStyleSheet(f"color:{Colors.ACCENT_GREEN}; font-size:10px; background:transparent;")
                row.setStyleSheet(
                    f"QFrame {{ border:none; border-left:4px solid {Colors.ACCENT_GREEN}; "
                    f"background-color: rgba(68,187,102,12); }}")
            elif i == index:
                dot.setText("●")
                dot.setStyleSheet(f"font-size:16px; color:{Colors.ACCENT_PRIMARY}; background:transparent;")
                title.setStyleSheet(f"color:{Colors.ACCENT_PRIMARY}; font-size:13px; font-weight:bold; "
                                    f"background:transparent;")
                sub.setStyleSheet(f"color:{Colors.TEXT_MAIN}; font-size:10px; background:transparent;")
                row.setStyleSheet(
                    f"QFrame {{ border:none; border-left:4px solid {Colors.ACCENT_PRIMARY}; "
                    f"background-color: rgba(255,204,68,14); }}")
            else:
                dot.setText("○")
                dot.setStyleSheet(f"font-size:16px; color:{Colors.BORDER}; background:transparent;")
                title.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:13px; font-weight:bold; "
                                    f"background:transparent;")
                sub.setStyleSheet(f"color:{Colors.BORDER}; font-size:10px; background:transparent;")
                row.setStyleSheet("QFrame { border:none; border-left:4px solid transparent; background-color:transparent; }")


def _compute_result_counts(tests: list[SessionTest]) -> dict:
    """Đếm Tổng số/Đã đo/Đạt/Không đạt/Chưa đo trên danh sách bài test — dùng
    chung cho thẻ tổng hợp Bước 2 và bảng kết quả tổng hợp Bước 3. Đạt/Không
    đạt tính theo ReportTable.confirmed_passed (đúng công thức đã dùng bởi
    CalibrationSession.all_passed), không suy diễn lại logic riêng."""
    total = len(tests)
    done = sum(1 for t in tests if t.status == "done")
    passed = sum(1 for t in tests if t.enabled and t.result_table is not None
                 and t.result_table.confirmed_passed is True)
    failed = sum(1 for t in tests if t.enabled and t.result_table is not None
                 and t.result_table.confirmed_passed is False)
    return {"total": total, "done": done, "passed": passed, "failed": failed,
            "pending": total - done}


def _make_stat_card(label: str, color: str) -> tuple[QFrame, QLabel]:
    """1 thẻ tổng hợp số liệu kiểu 'sum-card' (mockup Bước 2/3) — trả về
    (frame để add vào layout, label giá trị để cập nhật số sau này)."""
    card = QFrame()
    card.setObjectName("stat_card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(4)
    lbl = QLabel(label)
    lbl.setProperty("role", "stat_label")
    val = QLabel("0")
    val.setProperty("role", "stat_val")
    val.setStyleSheet(f"color:{color};")
    lay.addWidget(lbl)
    lay.addWidget(val)
    return card, val


def _field_col(label_text: str, widget) -> QVBoxLayout:
    """1 field kiểu mockup: nhãn ở TRÊN, ô nhập ở DƯỚI (khác kiểu form nhãn-trái
    truyền thống) — dùng trong _row3()/_row1()."""
    col = QVBoxLayout()
    col.setSpacing(4)
    lbl = QLabel(label_text)
    lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:12px; font-weight:bold; background:transparent;")
    col.addWidget(lbl)
    col.addWidget(widget)
    return col


def _row3(layout: QVBoxLayout, *pairs: tuple[str, object]):
    """Xếp tối đa 3 field (nhãn, widget) trên 1 hàng ngang, mỗi field chiếm
    tỉ lệ bằng nhau — khớp bố cục 3 cột của mockup. Hàng chưa đủ 3 field vẫn
    giữ đúng bề rộng 1/3 cho field đã có (không tự dãn ra hết hàng)."""
    row = QHBoxLayout()
    row.setSpacing(14)
    for label_text, widget in pairs:
        row.addLayout(_field_col(label_text, widget), 1)
    for _ in range(3 - len(pairs)):
        row.addStretch(1)
    layout.addLayout(row)


def _row1(layout: QVBoxLayout, label_text: str, widget):
    """1 field chiếm trọn hàng ngang (vd 'Phạm vi đo')."""
    layout.addLayout(_field_col(label_text, widget))


# ============================================================================
# Bước 1: Thông tin phiên
# ============================================================================

class _MetaTab(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        self.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Template ---
        tpl_group = QGroupBox("Mẫu báo cáo")
        tpl_lay = QVBoxLayout(tpl_group)
        tpl_lay.setSpacing(10)
        self.cmb_template = QComboBox()
        self.cmb_template.addItem("— Chọn mẫu báo cáo —", "")
        for tid, tname in list_templates():
            self.cmb_template.addItem(tname, tid)
        _row1(tpl_lay, "Loại thiết bị / mẫu:", self.cmb_template)
        layout.addWidget(tpl_group)

        # --- DUT --- (3 cột/hàng, nhãn trên - ô nhập dưới, khớp mockup)
        dut_group = QGroupBox("Thiết bị cần kiểm (DUT)")
        dut_lay = QVBoxLayout(dut_group)
        dut_lay.setSpacing(10)
        self.e_name   = QLineEdit()
        self.e_model  = QLineEdit()
        self.e_mfr    = QLineEdit()
        _row3(dut_lay, ("Tên phương tiện:", self.e_name), ("Ký hiệu:", self.e_model),
             ("Hãng sản xuất:", self.e_mfr))
        self.e_serial = QLineEdit()
        self.e_year   = QLineEdit()
        self.e_owner  = QLineEdit()
        _row3(dut_lay, ("Số serial:", self.e_serial), ("Năm sản xuất:", self.e_year),
             ("Đơn vị sử dụng:", self.e_owner))
        self.e_range  = QLineEdit()
        _row1(dut_lay, "Phạm vi đo:", self.e_range)
        layout.addWidget(dut_group)

        # --- Session meta --- (3 cột/hàng, nhãn trên - ô nhập dưới)
        meta_group = QGroupBox("Thông tin phiên kiểm định")
        meta_lay = QVBoxLayout(meta_group)
        meta_lay.setSpacing(10)
        self.e_operator  = QLineEdit()
        self.e_reviewer  = QLineEdit()
        self.e_manager   = QLineEdit()
        _row3(meta_lay, ("Kiểm định viên:", self.e_operator), ("Người soát lại:", self.e_reviewer),
             ("Thủ trưởng đơn vị:", self.e_manager))

        self.e_cert      = QLineEdit()
        self.e_location  = QLineEdit("Thành phố Hồ Chí Minh")
        self.e_equip     = QLineEdit()
        _row3(meta_lay, ("Số GCN/BB kiểm định:", self.e_cert), ("Địa điểm kiểm định:", self.e_location),
             ("Phương tiện kiểm định:", self.e_equip))

        self.e_temp      = QLineEdit()
        self.e_humidity  = QLineEdit()
        self.de_date = QDateEdit(QDate.currentDate())
        self.de_date.setCalendarPopup(True)
        self.de_date.setDisplayFormat("dd/MM/yyyy")
        _row3(meta_lay, ("Nhiệt độ:", self.e_temp), ("Độ ẩm:", self.e_humidity),
             ("Ngày kiểm định:", self.de_date))

        self.de_valid = QDateEdit(QDate.currentDate().addYears(1))
        self.de_valid.setCalendarPopup(True)
        self.de_valid.setDisplayFormat("dd/MM/yyyy")
        _row3(meta_lay, ("Hiệu lực đến:", self.de_valid))

        layout.addWidget(meta_group)
        layout.addStretch()

    def refresh_templates(self):
        """Nạp lại danh sách mẫu báo cáo (vd sau khi tạo 1 mẫu mới qua
        Template Scan Dialog) — giữ nguyên lựa chọn hiện tại nếu còn tồn tại."""
        current = self.cmb_template.currentData()
        self.cmb_template.blockSignals(True)
        self.cmb_template.clear()
        self.cmb_template.addItem("— Chọn mẫu báo cáo —", "")
        for tid, tname in list_templates():
            self.cmb_template.addItem(tname, tid)
        idx = self.cmb_template.findData(current)
        if idx >= 0:
            self.cmb_template.setCurrentIndex(idx)
        self.cmb_template.blockSignals(False)

    def load_from(self, session: CalibrationSession):
        m = session.meta
        idx = self.cmb_template.findData(session.template_id)
        if idx >= 0:
            self.cmb_template.setCurrentIndex(idx)
        self.e_name.setText(m.dut.name)
        self.e_model.setText(m.dut.model)
        self.e_serial.setText(m.dut.serial)
        self.e_year.setText(m.dut.manufacture_year)
        self.e_mfr.setText(m.dut.manufacturer)
        self.e_owner.setText(m.dut.owner)
        self.e_range.setText(m.dut.measurement_range)
        self.e_operator.setText(m.operator)
        self.e_reviewer.setText(m.reviewer)
        self.e_manager.setText(m.manager)
        self.e_cert.setText(m.cert_number)
        self.e_equip.setText(m.inspection_equipment)
        self.e_temp.setText(m.temperature)
        self.e_humidity.setText(m.humidity)
        self.e_location.setText(m.location)
        if m.date:
            self.de_date.setDate(QDate(m.date.year, m.date.month, m.date.day))
        if m.valid_until:
            self.de_valid.setDate(QDate(m.valid_until.year, m.valid_until.month, m.valid_until.day))

    def save_to(self, session: CalibrationSession):
        session.template_id = self.cmb_template.currentData() or ""
        m = session.meta
        m.dut.name              = self.e_name.text().strip()
        m.dut.model             = self.e_model.text().strip()
        m.dut.serial            = self.e_serial.text().strip()
        m.dut.manufacture_year  = self.e_year.text().strip()
        m.dut.manufacturer      = self.e_mfr.text().strip()
        m.dut.owner             = self.e_owner.text().strip()
        m.dut.measurement_range = self.e_range.text().strip()
        m.operator              = self.e_operator.text().strip()
        m.reviewer               = self.e_reviewer.text().strip()
        m.manager                = self.e_manager.text().strip()
        m.cert_number            = self.e_cert.text().strip()
        m.inspection_equipment   = self.e_equip.text().strip()
        m.temperature            = self.e_temp.text().strip()
        m.humidity               = self.e_humidity.text().strip()
        m.location               = self.e_location.text().strip()
        qd = self.de_date.date()
        m.date = date(qd.year(), qd.month(), qd.day())
        qv = self.de_valid.date()
        m.valid_until = date(qv.year(), qv.month(), qv.day())


# ============================================================================
# Bước 2: Danh sách bài đo — chạy test + rà soát/xác nhận từng dòng kết quả
# ============================================================================

class _TestReviewTab(QWidget):
    run_all_requested = pyqtSignal()
    run_one_requested = pyqtSignal(int)
    stop_requested     = pyqtSignal()
    open_scenario_requested = pyqtSignal(int)
    row_edited               = pyqtSignal()   # checkbox/combobox Đạt-Không đạt vừa đổi

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tests: list[SessionTest] = []
        self._template_id: str = ""
        self._current_index: Optional[int] = None
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Horizontal)

        # ── Trái: danh sách 8 bài test ──────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)

        info = QLabel("Chọn file kịch bản cho từng bài, chạy rồi bấm vào bài để rà soát "
                       "& xác nhận từng dòng kết quả bên phải.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        left_lay.addWidget(info)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self._stat_lbls: dict[str, QLabel] = {}
        for key, label, color in [
            ("total",   "Tổng số",    Colors.TEXT_MAIN),
            ("done",    "Đã đo",      Colors.ACCENT_PRIMARY),
            ("passed",  "Đạt",        Colors.ACCENT_GREEN),
            ("failed",  "Không đạt",  Colors.ACCENT_RED),
            ("pending", "Chưa đo",    Colors.TEXT_DIM),
        ]:
            card, val_lbl = _make_stat_card(label, color)
            stats_row.addWidget(card)
            self._stat_lbls[key] = val_lbl
        left_lay.addLayout(stats_row)

        self.table = QTableWidget(0, len(TEST_COLS))
        self._chk_header = CheckBoxHeader(self.table, label="")
        self._chk_header.setToolTip("Tick để chọn/bỏ chọn TẤT CẢ bài")
        self._chk_header.toggled_all.connect(self._toggle_all_enabled)
        self.table.setHorizontalHeader(self._chk_header)
        self.table.setHorizontalHeaderLabels(TEST_COLS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_CHK,    QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_TBL,    QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_NAME,   QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_FILE,   QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_CHK,    44)
        self.table.setColumnWidth(_COL_TBL,    52)
        self.table.setColumnWidth(_COL_STATUS, 190)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            # ::item:alternate:selected phải khai RIÊNG — nếu chỉ dựa vào
            # selection-background-color/selection-color ở cấp QTableWidget,
            # Qt ưu tiên rule ::item:alternate (chỉ có background, không có
            # color) cho các dòng xen kẽ, khiến chữ dòng đó vẫn đen khi chọn
            # dù dòng còn lại đã đúng màu (chẵn/lẻ khác nhau).
            f"QTableWidget::item:alternate {{ background-color: #1a1f26; }}"
            f"QTableWidget::item:selected {{ background-color: {Colors.ACCENT_PRIMARY};"
            f" color: {Colors.BG_WINDOW}; }}"
            f"QTableWidget::item:alternate:selected {{ background-color: {Colors.ACCENT_PRIMARY};"
            f" color: {Colors.BG_WINDOW}; }}"
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        left_lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.btn_choose = QPushButton("📂 Chọn file…")
        self.btn_choose.setToolTip("Chọn file .json cho bài test đang được bôi đen")
        self.btn_choose.clicked.connect(self._choose_file_selected)
        bar.addWidget(self.btn_choose)
        bar.addStretch()
        self.btn_run = QPushButton("▶ Chạy tất cả")
        self.btn_run.setStyleSheet(
            f"background:{Colors.ACCENT_PRIMARY}; color:{Colors.BG_WINDOW};"
            f" font-weight:bold; border:none; border-radius:6px; padding:8px 18px;")
        self.btn_run.clicked.connect(self.run_all_requested)
        bar.addWidget(self.btn_run)
        self.btn_stop = QPushButton("■ Dừng")
        self.btn_stop.setStyleSheet(
            f"background:{Colors.ACCENT_RED}; color:{Colors.BG_WINDOW};"
            f" font-weight:bold; border:none; border-radius:6px; padding:8px 18px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested)
        bar.addWidget(self.btn_stop)
        left_lay.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(18)
        left_lay.addWidget(self.progress)
        splitter.addWidget(left)

        # ── Phải: chi tiết bài đang chọn ─────────────────────────────────
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 0, 0, 0)

        self.lbl_title = QLabel("Chọn 1 bài test bên trái để xem chi tiết")
        self.lbl_title.setStyleSheet("font-weight:bold; font-size:12px;")
        right_lay.addWidget(self.lbl_title)

        file_bar = QHBoxLayout()
        self.e_file = QLineEdit()
        self.e_file.setReadOnly(True)
        file_bar.addWidget(self.e_file, 1)
        self.btn_choose_detail = QPushButton("📂 Chọn file kịch bản…")
        self.btn_choose_detail.clicked.connect(self._choose_file_detail)
        file_bar.addWidget(self.btn_choose_detail)
        self.btn_run_one = QPushButton("▶ Chạy bài này")
        self.btn_run_one.setEnabled(False)
        self.btn_run_one.clicked.connect(self._request_run_one)
        file_bar.addWidget(self.btn_run_one)
        right_lay.addLayout(file_bar)

        bulk_bar = QHBoxLayout()
        self.btn_check_all = QPushButton("☑ Chọn tất cả vào báo cáo")
        self.btn_check_all.setEnabled(False)
        self.btn_check_all.clicked.connect(lambda: self._set_all_confirmed(True))
        bulk_bar.addWidget(self.btn_check_all)
        self.btn_uncheck_all = QPushButton("☐ Bỏ chọn tất cả")
        self.btn_uncheck_all.setEnabled(False)
        self.btn_uncheck_all.clicked.connect(lambda: self._set_all_confirmed(False))
        bulk_bar.addWidget(self.btn_uncheck_all)
        bulk_bar.addStretch()
        right_lay.addLayout(bulk_bar)

        self._result_holder = QVBoxLayout()
        right_lay.addLayout(self._result_holder, 1)
        self._render_result_table("", [])

        splitter.addWidget(right)
        splitter.setSizes([460, 700])
        layout.addWidget(splitter, 1)

    # -- Nạp / làm mới danh sách -----------------------------------------

    def load_tests(self, tests: list[SessionTest], template_id: str = ""):
        self._tests = tests
        self._template_id = template_id
        self.table.setRowCount(0)
        for i, t in enumerate(tests):
            self._append_row(i, t)
        self._clear_detail()
        self._update_chk_header()
        self._update_summary_cards()

    def _update_summary_cards(self):
        counts = _compute_result_counts(self._tests)
        for key, lbl in self._stat_lbls.items():
            lbl.setText(str(counts[key]))

    def _make_enabled_cb(self, test: SessionTest):
        def _cb(state):
            test.enabled = state != 0
            self._update_chk_header()
        return _cb

    def _toggle_all_enabled(self, checked: bool):
        for row in range(self.table.rowCount()):
            cell_w = self.table.cellWidget(row, _COL_CHK)
            chk = cell_w.findChild(QCheckBox) if cell_w else None
            if chk:
                chk.setChecked(checked)

    def _update_chk_header(self):
        self._chk_header.setChecked(bool(self._tests) and all(t.enabled for t in self._tests))

    def _append_row(self, index: int, test: SessionTest):
        self.table.insertRow(index)

        chk = QCheckBox()
        chk.setChecked(test.enabled)
        chk.stateChanged.connect(self._make_enabled_cb(test))
        cell_w = QWidget()
        cell_lay = QHBoxLayout(cell_w)
        cell_lay.addWidget(chk); cell_lay.setAlignment(Qt.AlignCenter)
        cell_lay.setContentsMargins(4, 0, 4, 0)
        self.table.setCellWidget(index, _COL_CHK, cell_w)

        for col, text in [(_COL_TBL, test.table_id), (_COL_NAME, test.name)]:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(index, col, it)

        path_it = QTableWidgetItem(os.path.basename(test.scenario_path) if test.scenario_path else "")
        path_it.setFlags(path_it.flags() & ~Qt.ItemIsEditable)
        path_it.setForeground(QColor(Colors.TEXT_DIM if not test.scenario_path else Colors.TEXT_MAIN))
        if test.scenario_path:
            path_it.setToolTip(test.scenario_path)
        self.table.setItem(index, _COL_FILE, path_it)

        badge = QLabel("")
        badge_w = QWidget()
        badge_lay = QHBoxLayout(badge_w)
        badge_lay.addWidget(badge)
        badge_lay.setAlignment(Qt.AlignCenter)
        badge_lay.setContentsMargins(4, 2, 4, 2)
        self.table.setCellWidget(index, _COL_STATUS, badge_w)
        self._set_status_cell(index, test)

    def _set_status_cell(self, row: int, test: SessionTest):
        cell_w = self.table.cellWidget(row, _COL_STATUS)
        badge = cell_w.findChild(QLabel) if cell_w else None
        if badge:
            label, color = _test_status_label(test)
            _set_badge(badge, label, color)

    def refresh_statuses(self):
        for i, t in enumerate(self._tests):
            self._set_status_cell(i, t)
        self._update_summary_cards()

    def set_live_step_count(self, row: int, count: int):
        """Cập nhật cột Trạng thái theo thời gian thực khi 1 bài đang chạy —
        hiện số bước đã hoàn thành thay vì chỉ tĩnh 'Đang chạy'."""
        cell_w = self.table.cellWidget(row, _COL_STATUS)
        badge = cell_w.findChild(QLabel) if cell_w else None
        if badge:
            _set_badge(badge, f"▶ Đang chạy ({count} bước)", Colors.ACCENT_PRIMARY)

    def refresh_row(self, index: int):
        if 0 <= index < len(self._tests):
            self._set_status_cell(index, self._tests[index])
            if index == self._current_index:
                self._show_test(index)
        self._update_summary_cards()

    # -- Chọn dòng / hiển thị chi tiết ------------------------------------

    def _on_selection_changed(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if rows:
            self._show_test(rows[0])

    def _on_cell_double_clicked(self, row: int, col: int):
        if col in (_COL_NAME, _COL_FILE):
            self.open_scenario_requested.emit(row)

    def _clear_detail(self):
        self._current_index = None
        self.lbl_title.setText("Chọn 1 bài test bên trái để xem chi tiết")
        self.e_file.setText("")
        self.btn_run_one.setEnabled(False)
        self.btn_check_all.setEnabled(False)
        self.btn_uncheck_all.setEnabled(False)
        self._render_result_table("", [])

    def _show_test(self, row: int):
        if row < 0 or row >= len(self._tests):
            return
        self._current_index = row
        test = self._tests[row]
        self.lbl_title.setText(f"{test.table_id}: {test.name}")
        self.e_file.setText(test.scenario_path or "(chưa chọn file kịch bản)")
        self.btn_run_one.setEnabled(not self._running)
        has_result = test.result_table is not None
        rows = test.result_table.rows if has_result else self._preview_rows(test)
        note = test.result_table.note if has_result else ""
        self._render_result_table(test.table_id, rows, with_checkbox=has_result, note=note)
        self.btn_check_all.setEnabled(has_result and bool(rows))
        self.btn_uncheck_all.setEnabled(has_result and bool(rows))

    def _preview_rows(self, test: SessionTest) -> list:
        """Bài chưa chạy (result_table=None) -> dựng khung bảng theo đúng mẫu
        báo cáo (đủ số dòng, giá trị để trống) để xem trước cấu trúc đo,
        không cho xác nhận (chưa có gì để xác nhận)."""
        return _scaffold_rows(self._template_id, test)

    def _render_result_table(self, table_id: str, rows, with_checkbox: bool = True, note: str = ""):
        while self._result_holder.count():
            item = self._result_holder.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if note:
            lbl = QLabel(f"⚠ {note}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{Colors.ACCENT_WARN}; font-size:11px;")
            self._result_holder.addWidget(lbl)
        # Luôn HIỆN cả 2 cột (checkbox + Đạt/Không đạt); with_checkbox ở đây
        # chỉ còn ý nghĩa "bài đã có kết quả thật" (interactive) -> nếu bài
        # chưa chạy (khung xem trước rỗng) thì 2 cột vẫn hiện nhưng bị khoá,
        # tránh tick/chọn trên dữ liệu chưa tồn tại rồi mất khi đổi bài khác.
        tbl = build_wysiwyg_table(self._template_id, table_id, rows,
                                  with_checkbox=True, on_toggle=self._on_row_confirm_toggled,
                                  with_status=True, on_status_change=self._on_row_confirm_toggled,
                                  interactive=with_checkbox,
                                  on_value_edited=self._on_value_edited,
                                  empty_message="Chưa có kết quả",
                                  recompute_row=_make_recompute_row(self._template_id, table_id),
                                  measured_counts=_measured_counts_for(self._template_id, table_id, len(rows)))
        self._result_holder.addWidget(tbl)

    def _on_value_edited(self):
        """Kiểm định viên vừa sửa tay 1 giá trị đo — dựng lại đúng bảng đang
        xem để thấy ngay giá trị mới + màu đánh dấu đã sửa."""
        if self._current_index is not None:
            self._show_test(self._current_index)

    def _on_row_confirm_toggled(self):
        if self._current_index is not None and self._current_index < len(self._tests):
            self._set_status_cell(self._current_index, self._tests[self._current_index])
        self._update_summary_cards()
        self.row_edited.emit()

    def _set_all_confirmed(self, value: bool):
        if self._current_index is None:
            return
        test = self._tests[self._current_index]
        if not test.result_table:
            return
        for r in test.result_table.rows:
            r.confirmed = value
        self._render_result_table(test.table_id, test.result_table.rows, note=test.result_table.note)
        self._set_status_cell(self._current_index, test)
        self._update_summary_cards()

    # -- Chọn file kịch bản -------------------------------------------------

    def _choose_file_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn (bôi đen) một bài test trong bảng.")
            return
        self._pick_file_for_row(rows[0])

    def _choose_file_detail(self):
        if self._current_index is None:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một bài test trong bảng bên trái.")
            return
        self._pick_file_for_row(self._current_index)

    def _pick_file_for_row(self, row: int):
        start_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file kịch bản", start_dir, "JSON (*.json)")
        if not path:
            return
        test = self._tests[row]
        test.scenario_path = path
        it = self.table.item(row, _COL_FILE)
        if it:
            it.setText(os.path.basename(path))
            it.setToolTip(path)
            it.setForeground(QColor(Colors.TEXT_MAIN))
        if row == self._current_index:
            self.e_file.setText(path)

    # -- Chạy test ---------------------------------------------------------

    def _request_run_one(self):
        if self._current_index is not None:
            self.run_one_requested.emit(self._current_index)

    def set_running(self, running: bool):
        self._running = running
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.progress.setVisible(running)
        if self._current_index is not None:
            self.btn_run_one.setEnabled(not running)

    def set_progress(self, current: int, total: int):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        self.progress.setFormat(f"Bài {current}/{total}")


# ============================================================================
# Bước 3: Xuất báo cáo — preview trong app + xuất & mở file
# ============================================================================

_AUTO_CONCLUSION_PASS = "Đạt yêu cầu kỹ thuật đo lường"
_AUTO_CONCLUSION_FAIL = "Không đạt yêu cầu kỹ thuật đo lường"


class _ExportTab(QWidget):
    export_bienban_requested = pyqtSignal()
    export_gcnkd_requested   = pyqtSignal()
    print_requested          = pyqtSignal()
    row_edited               = pyqtSignal()   # checkbox/combobox trong bảng xem trước vừa đổi

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Horizontal)

        export_btn_style = (
            f"QPushButton {{ background:#0a2418; color:{Colors.ACCENT_GREEN}; "
            f"border:1px solid {Colors.ACCENT_GREEN}; font-weight:bold; padding:8px 16px; }}"
            f"QPushButton:hover {{ background:#0e3320; }}"
            f"QPushButton:disabled {{ background:transparent; color:{Colors.TEXT_DIM}; "
            f"border-color:{Colors.BORDER}; }}"
        )

        # ── Trái: loại tài liệu + tổng hợp + xuất ────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(10)

        # -- Loại tài liệu --
        doc_group = QGroupBox("Loại tài liệu")
        doc_lay = QVBoxLayout(doc_group)
        self._doc_type = "bienban"
        self._doc_btns: dict[str, QPushButton] = {}
        doc_row1 = QHBoxLayout()
        for key, text in (("bienban", "Biên Bản kiểm định"), ("gcnkd", "Giấy Chứng Nhận")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self._set_doc_type(k))
            doc_row1.addWidget(b)
            self._doc_btns[key] = b
        doc_lay.addLayout(doc_row1)
        b_both = QPushButton("Cả hai tài liệu")
        b_both.setCheckable(True)
        b_both.clicked.connect(lambda _c=False: self._set_doc_type("both"))
        doc_lay.addWidget(b_both)
        self._doc_btns["both"] = b_both
        left_lay.addWidget(doc_group)

        left_lay.addWidget(QLabel("Tổng hợp các bài test:"))
        self.lst_tests = QListWidget()
        self.lst_tests.setMaximumHeight(150)
        left_lay.addWidget(self.lst_tests)

        rs_frame = QFrame()
        rs_frame.setObjectName("result_summary")
        rs_frame.setStyleSheet(
            f"QFrame#result_summary {{ background-color:{Colors.BG_DEEP}; "
            f"border:1px solid {Colors.BORDER}; }}")
        rs_lay = QVBoxLayout(rs_frame)
        rs_lay.setContentsMargins(10, 8, 10, 8)
        rs_lay.setSpacing(4)
        self._rs_vals: dict[str, QLabel] = {}
        for key, label, color in [
            ("total",  "Tổng điểm đo",   Colors.ACCENT_PRIMARY),
            ("passed", "Đạt yêu cầu",    Colors.ACCENT_GREEN),
            ("failed", "Không đạt",      Colors.ACCENT_RED),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px; background:transparent;")
            val = QLabel("0")
            val.setStyleSheet(f"color:{color}; font-size:12px; font-weight:bold; background:transparent;")
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            rs_lay.addLayout(row)
            self._rs_vals[key] = val
        concl_sum_row = QHBoxLayout()
        concl_sum_lbl = QLabel("Kết luận tổng")
        concl_sum_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px; background:transparent;")
        self._rs_conclusion_val = QLabel("—")
        self._rs_conclusion_val.setStyleSheet(
            f"color:{Colors.TEXT_DIM}; font-size:12px; font-weight:bold; background:transparent;")
        concl_sum_row.addWidget(concl_sum_lbl)
        concl_sum_row.addStretch()
        concl_sum_row.addWidget(self._rs_conclusion_val)
        rs_lay.addLayout(concl_sum_row)
        left_lay.addWidget(rs_frame)

        self.lbl_warning = QLabel("")
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet(f"color:{Colors.ACCENT_WARN}; font-size:11px;")
        left_lay.addWidget(self.lbl_warning)

        # Kết luận — đặt ở đây (không phải Bước 1) vì chỉ tính được đúng
        # SAU khi biết kết quả Đạt/Không đạt của các bài test. Tự động theo
        # all_passed (Đạt nếu mọi bài đã xác nhận đều đạt, Không đạt nếu có
        # bài không đạt) — refresh() chỉ ghi đè khi người dùng CHƯA tự gõ
        # tay (self._conclusion_manual), gõ tay lúc nào cũng được và giữ
        # nguyên cho tới khi mở/tạo phiên khác.
        concl_row = QHBoxLayout()
        concl_row.addWidget(QLabel("Kết luận:"))
        self.e_conclusion = QLineEdit()
        self.e_conclusion.setToolTip(
            "Tự động theo kết quả: \"Đạt yêu cầu kỹ thuật đo lường\" nếu mọi bài đã "
            "xác nhận đều Đạt, \"Không đạt...\" nếu có bài Không đạt. Gõ tay để ghi đè.")
        self.e_conclusion.textEdited.connect(self._on_conclusion_edited)
        concl_row.addWidget(self.e_conclusion, 1)
        left_lay.addLayout(concl_row)
        self._conclusion_manual = False

        lbl_hint = QLabel("Xem trước trước khi xuất để kiểm tra nội dung.")
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
        left_lay.addWidget(lbl_hint)
        left_lay.addStretch()

        action_row = QHBoxLayout()
        self.btn_print = QPushButton("🖨 In trực tiếp")
        self.btn_print.setEnabled(False)
        self.btn_print.setToolTip("In file vừa xuất gần nhất (chưa xuất lần nào thì chưa in được)")
        self.btn_print.clicked.connect(self.print_requested)
        action_row.addWidget(self.btn_print)
        self.btn_export = QPushButton("📤 Xuất tài liệu")
        self.btn_export.setEnabled(False)
        self.btn_export.setStyleSheet(export_btn_style)
        self.btn_export.clicked.connect(self._on_export_clicked)
        action_row.addWidget(self.btn_export)
        left_lay.addLayout(action_row)

        splitter.addWidget(left)
        self._set_doc_type("bienban")

        # ── Phải: xem trước tài liệu (nền giấy) ──────────────────────────
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 0, 0, 0)

        preview_bar = QHBoxLayout()
        self.btn_preview = QPushButton("🔍 Xem trước nội dung báo cáo")
        self.btn_preview.clicked.connect(self._build_preview)
        preview_bar.addWidget(self.btn_preview)
        preview_bar.addStretch()
        right_lay.addLayout(preview_bar)

        self.preview_area = QScrollArea()
        self.preview_area.setObjectName("doc_preview_area")
        self.preview_area.setWidgetResizable(True)
        # Mô phỏng nền giấy của tài liệu thật (khác nền tối chung của app) —
        # chỉ áp dụng cho CÂY con của preview_area (bảng WYSIWYG bên trong),
        # không đụng tới QTableWidget toàn app (Bước 2 vẫn giữ theme tối).
        self.preview_area.setStyleSheet(f"""
            QScrollArea#doc_preview_area {{ background:#f0ece0; border:1px solid {Colors.BORDER}; }}
            QScrollArea#doc_preview_area QWidget {{ background:#f0ece0; }}
            QScrollArea#doc_preview_area QLabel {{ color:#1a1a1a; background:transparent; }}
            QScrollArea#doc_preview_area QTableWidget {{ background:#ffffff; color:#1a1a1a;
                gridline-color:#bbbbbb; border:1px solid #999999; }}
            QScrollArea#doc_preview_area QTableWidget::item {{ color:#1a1a1a; }}
            QScrollArea#doc_preview_area QTableWidget::item:selected {{
                background:#cfe8ff; color:#1a1a1a; }}
            QScrollArea#doc_preview_area QHeaderView::section {{ background:#333333;
                color:#ffffff; border:1px solid #666666; padding:5px; }}
            QScrollArea#doc_preview_area QComboBox {{ background:#ffffff; color:#1a1a1a;
                border:1px solid #999999; }}
            QScrollArea#doc_preview_area QComboBox QAbstractItemView {{ background:#ffffff;
                color:#1a1a1a; selection-background-color:#cfe8ff; selection-color:#1a1a1a; }}
            QScrollArea#doc_preview_area QCheckBox {{ background:transparent; }}
        """)
        self._preview_inner = QWidget()
        self._preview_lay = QVBoxLayout(self._preview_inner)
        self._preview_lay.addWidget(QLabel(
            "Chọn 1 bài bên trái rồi bấm 'Xem trước' để chỉ xem đúng bài đó "
            "(không chọn gì thì xem toàn bộ) — kể cả bài chưa chạy (khung "
            "trống) hoặc chưa xác nhận đủ dòng. Chỉ những dòng có tick "
            "'Đưa vào báo cáo' mới thực sự được xuất."))
        self._preview_lay.addStretch()
        self.preview_area.setWidget(self._preview_inner)
        right_lay.addWidget(self.preview_area, 1)

        splitter.addWidget(right)
        splitter.setSizes([340, 880])
        layout.addWidget(splitter, 1)

        self._tests: list[SessionTest] = []
        self._template_id: str = ""

    def _set_doc_type(self, key: str):
        self._doc_type = key
        for k, b in self._doc_btns.items():
            sel = k == key
            b.setChecked(sel)
            if sel:
                b.setStyleSheet(
                    f"background:#1e1a08; color:{Colors.ACCENT_PRIMARY}; "
                    f"border:1px solid {Colors.ACCENT_PRIMARY}; font-weight:bold; padding:8px 10px;")
            else:
                b.setStyleSheet(
                    f"background:{Colors.BG_INPUT}; color:{Colors.TEXT_DIM}; "
                    f"border:1px solid {Colors.BORDER}; padding:8px 10px;")

    def _on_export_clicked(self):
        if self._doc_type in ("bienban", "both"):
            self.export_bienban_requested.emit()
        if self._doc_type in ("gcnkd", "both"):
            self.export_gcnkd_requested.emit()

    def set_print_enabled(self, enabled: bool):
        self.btn_print.setEnabled(enabled)

    def _on_conclusion_edited(self, _text: str):
        self._conclusion_manual = True

    def load_conclusion(self, text: str):
        """Nạp kết luận đã lưu (mở phiên cũ) hoặc mặc định (phiên mới) — gọi
        1 lần khi nạp phiên, TRƯỚC refresh(). Coi là 'đã tự gõ tay' nếu
        khác 2 câu tự động, để không bị refresh() ghi đè mất lựa chọn cũ."""
        self.e_conclusion.setText(text)
        self._conclusion_manual = text not in (_AUTO_CONCLUSION_PASS, _AUTO_CONCLUSION_FAIL)

    def conclusion_text(self) -> str:
        return self.e_conclusion.text().strip()

    def refresh(self, tests: list[SessionTest], all_passed: Optional[bool], template_id: str = ""):
        self._tests = tests
        self._template_id = template_id
        counts = _compute_result_counts(tests)
        self._rs_vals["total"].setText(str(counts["total"]))
        self._rs_vals["passed"].setText(str(counts["passed"]))
        self._rs_vals["failed"].setText(str(counts["failed"]))
        self.lst_tests.clear()
        n_partial = 0
        for t in tests:
            if not t.enabled:
                self.lst_tests.addItem(f"—  {t.table_id}: {t.name}")
                continue
            rows = t.result_table.rows if t.result_table else []
            n = len(rows)
            c = sum(1 for r in rows if r.confirmed)
            if n == 0:
                icon = "⏳"
            elif c == 0:
                icon = "🟡"
                n_partial += 1
            elif c == n:
                icon = "✅"
            else:
                icon = "🔶"
                n_partial += 1
            self.lst_tests.addItem(f"{icon}  {t.table_id}: {t.name}  ({c}/{n})")

        # Luôn cho phép xem trước/xuất — kể cả khi chưa chạy Bước 2 hoặc dữ
        # liệu chưa đầy đủ; phần chưa có/chưa xác nhận sẽ để trống trong báo
        # cáo (report_generator đã tự xử lý an toàn, không crash).
        if all_passed is None:
            self._rs_conclusion_val.setText("CHỜ XÁC NHẬN")
            self._rs_conclusion_val.setStyleSheet(
                f"color:{Colors.TEXT_DIM}; font-size:12px; font-weight:bold; background:transparent;")
        else:
            ok = all_passed is True
            self._rs_conclusion_val.setText("ĐẠT" if ok else "KHÔNG ĐẠT")
            self._rs_conclusion_val.setStyleSheet(
                f"color:{Colors.ACCENT_GREEN if ok else Colors.ACCENT_RED}; "
                f"font-size:12px; font-weight:bold; background:transparent;")
        if not self._conclusion_manual:
            self.e_conclusion.setText(_AUTO_CONCLUSION_FAIL if all_passed is False
                                      else _AUTO_CONCLUSION_PASS)
        self.btn_export.setEnabled(True)

        if n_partial:
            self.lbl_warning.setText(
                f"⚠ Còn {n_partial} bài chưa xác nhận đủ dòng kết quả — "
                f"phần chưa xác nhận sẽ để trống trong báo cáo.")
        else:
            self.lbl_warning.setText("")

    def _build_preview(self):
        while self._preview_lay.count():
            item = self._preview_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()   # ẩn ngay — deleteLater() chỉ xoá thật ở vòng event loop sau
                w.deleteLater()

        # Có bài đang được chọn bên trái -> chỉ xem đúng bài đó; không chọn
        # gì (currentRow() == -1) -> xem toàn bộ như trước.
        sel_row = self.lst_tests.currentRow()
        targets = [self._tests[sel_row]] if 0 <= sel_row < len(self._tests) else self._tests

        any_shown = False
        for t in targets:
            if not t.enabled:
                if len(targets) == 1:
                    self._preview_lay.addWidget(QLabel(
                        f"{t.table_id} — {t.name}: bài này đã bị bỏ qua (tắt), "
                        "không có trong báo cáo."))
                    any_shown = True
                continue
            has_result = t.result_table is not None
            rows = t.result_table.rows if has_result else _scaffold_rows(self._template_id, t)
            if not rows:
                continue
            any_shown = True
            title_text = f"{t.table_id} — {t.name}"
            if not has_result:
                title_text += "  (chưa chạy — khung xem trước)"
            title = QLabel(title_text)
            title.setStyleSheet("font-weight:bold; color:#8a6a10; font-size:12px;")
            self._preview_lay.addWidget(title)
            if has_result and t.result_table.note:
                note_lbl = QLabel(f"⚠ {t.result_table.note}")
                note_lbl.setWordWrap(True)
                note_lbl.setStyleSheet("color:#a85c00; font-size:11px;")
                self._preview_lay.addWidget(note_lbl)
            tbl = build_wysiwyg_table(self._template_id, t.table_id, rows,
                                      with_checkbox=True, on_toggle=self._on_row_edited,
                                      with_status=True, on_status_change=self._on_row_edited,
                                      interactive=has_result,
                                      on_value_edited=self._build_preview,
                                      recompute_row=_make_recompute_row(self._template_id, t.table_id),
                                      measured_counts=_measured_counts_for(self._template_id, t.table_id, len(rows)))
            # Dùng số DÒNG LƯỚI thật của bảng đã dựng (tbl.rowCount()), không
            # phải len(rows) (số TableRow logic) — bảng A1 gộp raw_readings
            # của 1 TableRow thành N dòng lưới hiển thị, nên 2 con số này
            # khác nhau; dùng nhầm len(rows) khiến bảng A1 bị nén chỉ còn đủ
            # chỗ cho ~2 dòng, cắt mất phần lớn dữ liệu.
            # setFixedHeight (không phải setMaximumHeight): layout chỉ cấp
            # đúng bằng sizeHint() nếu không ép cứng chiều cao, mà sizeHint
            # mặc định của QTableWidget KHÔNG tính theo số dòng thật -> bảng
            # bị co lại nhỏ hơn maximumHeight rồi tự sinh thanh cuộn dọc
            # riêng bên trong, dù đã đủ chỗ. Ép cứng chiều cao để hiện đủ
            # toàn bộ dòng, không cuộn — cuộn tổng thể do QScrollArea bên
            # ngoài (self.preview_area) đảm nhiệm.
            tbl.setFixedHeight(34 * (tbl.rowCount() + 1) + 16)
            tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._preview_lay.addWidget(tbl)

        if not any_shown:
            self._preview_lay.addWidget(QLabel("Chưa có bài test nào để xem trước."))
        self._preview_lay.addStretch()

    def _on_row_edited(self):
        """Checkbox/combobox trong bảng xem trước vừa đổi — chỉ báo lên
        SessionManagerWindow để làm mới cột tổng hợp bên trái (icon xác
        nhận, kết luận, nút xuất); KHÔNG tự dựng lại bảng xem trước (tránh
        dòng biến mất đột ngột ngay dưới con trỏ khi vừa bỏ tick — "Xem
        trước" vẫn là thao tác thủ công qua nút bấm)."""
        self.row_edited.emit()


# ============================================================================
# Cửa sổ chính: SessionManagerWindow
# ============================================================================

class SessionManagerWindow(QMainWindow):
    """Cửa sổ chính của ứng dụng — quản lý phiên kiểm định."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FREQ-CAL PRO :: Phiên Kiểm Định")
        self.setWindowIcon(QIcon("gui/logo.png"))
        self.resize(1600, 900)
        self.setMinimumSize(1100, 680)

        self._session = CalibrationSession()
        self._worker: _TestWorker | None = None
        self._current_test_index = -1
        self._step_results_current: list[StepResult] = []
        self._run_mode = "all"   # "all" | "single" — quyết định có chạy tiếp bài kế không
        self._last_export_path: str = ""

        # Kết nối thiết bị — dùng chung với Scenario Builder
        self._profile = None
        self.address_map: dict[str, str] = {}
        self.cmd_delay_s: float = 0.1

        # Cửa sổ Scenario Builder (mở khi cần, không modal)
        self._scenario_win = None

        self._build_ui()
        self._auto_load_profile()
        self._on_template_changed()   # load default tests khi khởi động

    # -------------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        head_frame = QFrame()
        head_frame.setObjectName("app_header")
        head = QHBoxLayout(head_frame)
        head.setContentsMargins(12, 8, 12, 8)
        logo_lbl = QLabel()
        pix = QPixmap("gui/logo.png").scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_lbl.setPixmap(pix)
        head.addWidget(logo_lbl)
        title = QLabel("Phiên Kiểm Định")
        title.setStyleSheet("font-size:16pt; font-weight:bold;")
        head.addWidget(title)
        head.addStretch()
        root.addWidget(head_frame)

        # ── Toolbar ───────────────────────────────────────────────────────────
        tool_frame = QFrame()
        tool_frame.setObjectName("app_toolbar")
        bar = QHBoxLayout(tool_frame)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(6)

        def mkbtn(text, slot, color=None, tip=""):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if color:
                b.setStyleSheet(
                    f"background:{color}; color:{Colors.BG_WINDOW}; font-weight:bold;"
                    f" border:none; border-radius:6px; padding:8px 14px;")
            if tip:
                b.setToolTip(tip)
            bar.addWidget(b)
            return b

        mkbtn("🔌 Thiết bị", self._open_device_manager,
              tip="Kết nối / quét thiết bị VISA")
        mkbtn("🔧 Kịch bản", self._open_scenario_builder, Colors.ACCENT_PRIMARY,
              tip="Mở Scenario Builder để xây dựng / chỉnh sửa kịch bản test")
        mkbtn("🗂 Quản lý mẫu báo cáo", self._open_template_manager,
              tip="Sửa lại hoặc sao chép 1 mẫu báo cáo đã có (Thông tin chung / Bảng dữ liệu / File Word)")
        bar.addStretch()

        self._lbl_devices = QLabel("Chưa kết nối thiết bị")
        self._lbl_devices.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")
        bar.addWidget(self._lbl_devices)
        bar.addStretch()

        mkbtn("🆕 Mới",        self._new_session)
        mkbtn("📂 Mở phiên…",  self._load_session)
        mkbtn("💾 Lưu phiên…", self._save_session)
        root.addWidget(tool_frame)

        # ── Step wizard (rail trái + nội dung phải) ──────────────────────────
        content = QWidget()
        content_lay = QHBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        steps = [
            ("Bước 1: Thông tin phiên",  "Thông tin DUT & phiên kiểm định"),
            ("Bước 2: Danh sách bài đo", "Chạy bài test & xác nhận kết quả"),
            ("Bước 3: Xuất báo cáo",     "Xem trước & xuất Biên Bản / GCN"),
        ]
        self.rail = _StepRail(steps)
        self.rail.setFixedWidth(240)
        self.stack = QStackedWidget()

        self._step_meta   = _MetaTab()
        self._step_review = _TestReviewTab()
        self._step_export = _ExportTab()
        self.stack.addWidget(self._step_meta)
        self.stack.addWidget(self._step_review)
        self.stack.addWidget(self._step_export)

        content_lay.addWidget(self.rail)
        content_lay.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.rail.step_clicked.connect(self.stack.setCurrentIndex)
        self.stack.currentChanged.connect(self._on_step_changed)

        self.statusBar().showMessage("Sẵn sàng.")

        # Wire signals
        self._step_meta.cmb_template.currentIndexChanged.connect(self._on_template_changed)
        self._step_review.run_all_requested.connect(self._run_all)
        self._step_review.stop_requested.connect(self._stop_run)
        self._step_review.run_one_requested.connect(self._run_one)
        self._step_review.open_scenario_requested.connect(self._open_scenario_for_test)
        self._step_export.export_bienban_requested.connect(self._export_bienban)
        self._step_export.export_gcnkd_requested.connect(self._export_gcnkd)
        self._step_export.print_requested.connect(self._print_last_export)
        self._step_export.row_edited.connect(self._refresh_export_tab)
        self._step_review.row_edited.connect(self._refresh_export_tab)

    def _on_step_changed(self, index: int):
        self.rail.set_current(index)
        if index == 2:
            self._refresh_export_tab()

    # -------------------------------------------------------------------------
    # Auto-load profile
    # -------------------------------------------------------------------------

    def _auto_load_profile(self):
        """Nạp địa chỉ từ profile đã lưu — KHÔNG gửi *IDN? nên KHÔNG đánh dấu là kết nối.
        Người dùng phải bấm 'Thiết bị' để xác nhận thực sự."""
        import os as _os
        from core.profile import ConnectionProfile
        path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                             "connection_profile.json")
        if not _os.path.exists(path):
            return
        try:
            prof = ConnectionProfile.load_json(path)
            if not prof.entries:
                return
            self._profile = prof
            self.address_map = prof.address_map()
            self.cmd_delay_s = prof.cmd_delay_ms / 1000.0
            self._update_device_label(verified=False)
            self._log(
                f"Đã tải profile: {', '.join(self.address_map)} "
                f"— chưa xác nhận kết nối (bấm 🔌 Thiết bị để kiểm tra).",
                Colors.ACCENT_WARN,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"Không nạp được connection_profile.json: {exc}", Colors.ACCENT_WARN)

    def _update_device_label(self, verified: bool = True):
        if self.address_map:
            keys = ", ".join(self.address_map.keys())
            if verified:
                self._lbl_devices.setText(f"🟢 Đã xác nhận: {keys}")
                self._lbl_devices.setStyleSheet(f"color:{Colors.ACCENT_GREEN}; font-size:11px;")
            else:
                self._lbl_devices.setText(f"⚠️ Profile: {keys}  (chưa xác nhận *IDN?)")
                self._lbl_devices.setStyleSheet(f"color:{Colors.ACCENT_WARN}; font-size:11px;")
        else:
            self._lbl_devices.setText("Chưa kết nối thiết bị")
            self._lbl_devices.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:11px;")

    # -------------------------------------------------------------------------
    # Device Manager
    # -------------------------------------------------------------------------

    def _open_device_manager(self):
        from gui.device_manager import DeviceManagerDialog
        from core.profile import ConnectionProfile
        prof = self._profile or ConnectionProfile()
        dlg = DeviceManagerDialog(self, mock=False, profile=prof)
        if dlg.exec_() == QDialog.Accepted:
            self._profile = dlg.get_profile()
            self.address_map = self._profile.address_map()
            self.cmd_delay_s = self._profile.cmd_delay_ms / 1000.0
            # verified=True: DeviceManagerDialog đã gửi *IDN? và xác nhận kết nối thật
            self._update_device_label(verified=True)
            self._log(f"Đã xác nhận {len(self.address_map)} thiết bị: "
                      f"{', '.join(self.address_map) or '(trống)'}", Colors.ACCENT_GREEN)
            # Đồng bộ sang Scenario Builder nếu đang mở
            if self._scenario_win and self._scenario_win.isVisible():
                self._scenario_win.address_map = dict(self.address_map)
                self._scenario_win._connected_keys = set(self.address_map.keys())
                self._scenario_win.cmd_delay_s = self.cmd_delay_s

    # -------------------------------------------------------------------------
    # Quản lý mẫu báo cáo — sửa/sao chép 1 mẫu đã có, không cần sửa code
    # -------------------------------------------------------------------------

    def _open_template_manager(self):
        from gui.template_manager_dialog import TemplateManagerDialog
        dlg = TemplateManagerDialog(self)
        dlg.exec_()
        if dlg.changed:
            self._step_meta.refresh_templates()
            self._log("Đã cập nhật mẫu báo cáo — bấm 'Mới' rồi chọn lại mẫu để thấy thay đổi.",
                      Colors.ACCENT_GREEN)

    # -------------------------------------------------------------------------
    # Scenario Builder
    # -------------------------------------------------------------------------

    def _open_scenario_builder(self):
        from gui.scenario_grid import ScenarioGridWindow
        if self._scenario_win is None or not self._scenario_win.isVisible():
            self._scenario_win = ScenarioGridWindow(
                parent=None,
                address_map=dict(self.address_map),
                cmd_delay_s=self.cmd_delay_s,
                on_device_changed=self._on_scenario_builder_device_changed,
            )
            self._scenario_win.show()
        else:
            self._scenario_win.raise_()
            self._scenario_win.activateWindow()

    def _open_scenario_for_test(self, index: int):
        test = self._session.tests[index]
        if not test.scenario_path or not os.path.isfile(test.scenario_path):
            QMessageBox.information(self, "Chưa có file",
                                    "Bài này chưa chọn file kịch bản hợp lệ.")
            return
        self._open_scenario_builder()
        if not self._scenario_win.load_scenario_file(test.scenario_path):
            return
        self._scenario_win.raise_()
        self._scenario_win.activateWindow()

    def _on_scenario_builder_device_changed(self, address_map: dict, cmd_delay_s: float):
        """Callback khi Scenario Builder cập nhật thiết bị — đồng bộ ngược lại."""
        self.address_map = address_map
        self.cmd_delay_s = cmd_delay_s
        self._update_device_label()

    # -------------------------------------------------------------------------
    # Template
    # -------------------------------------------------------------------------

    def _on_template_changed(self):
        tid = self._step_meta.cmb_template.currentData()
        if not tid:
            return
        try:
            tpl = get_template(tid)
        except KeyError:
            return

        if not self._session.tests:
            # Phiên trống (mới khởi động / vừa "Mới") -> nạp mặc định luôn.
            self._apply_template_defaults(tpl, tid)
            return

        if tid == self._session.template_id:
            return  # combobox đang được đồng bộ theo phiên đã nạp, không phải người dùng đổi

        # Người dùng chủ động đổi mẫu khi phiên đã có dữ liệu -> xác nhận vì sẽ
        # thay toàn bộ danh sách bài test hiện tại bằng mặc định của mẫu mới.
        if QMessageBox.question(
                self, "Đổi mẫu báo cáo",
                "Đổi mẫu báo cáo sẽ thay toàn bộ danh sách bài test hiện tại "
                "(và kết quả đã chạy) bằng danh sách mặc định của mẫu mới. "
                "Tiếp tục?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            idx = self._step_meta.cmb_template.findData(self._session.template_id)
            if idx >= 0:
                self._step_meta.cmb_template.blockSignals(True)
                self._step_meta.cmb_template.setCurrentIndex(idx)
                self._step_meta.cmb_template.blockSignals(False)
            return

        self._apply_template_defaults(tpl, tid)

    def _apply_template_defaults(self, tpl, tid: str):
        self._session.template_id = tid
        tpl.fill_session_defaults(self._session)
        self._session.tests = tpl.default_tests()
        self._step_meta.load_from(self._session)
        self._step_review.load_tests(self._session.tests, tid)
        self._step_export.load_conclusion(self._session.meta.conclusion)
        self._refresh_export_tab()
        self.rail.set_template_info(tpl.STANDARD, tpl.TEMPLATE_NAME)

    # -------------------------------------------------------------------------
    # Mới / Mở / Lưu phiên
    # -------------------------------------------------------------------------

    def _new_session(self):
        if QMessageBox.question(self, "Tạo phiên mới",
                                "Tạo phiên kiểm định mới? Dữ liệu hiện tại sẽ bị xóa.",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._session = CalibrationSession()
        self._on_template_changed()
        self._refresh_export_tab()
        self._log("Đã tạo phiên mới.", Colors.ACCENT_PRIMARY)

    def _load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở phiên kiểm định", "", "JSON (*.json)")
        if not path:
            return
        try:
            self._session = CalibrationSession.load_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi mở file", str(exc)); return
        self._step_meta.load_from(self._session)
        self._step_review.load_tests(self._session.tests, self._session.template_id)
        self._step_export.load_conclusion(self._session.meta.conclusion)
        self._refresh_export_tab()
        if self._session.template_id:
            try:
                tpl = get_template(self._session.template_id)
                self.rail.set_template_info(tpl.STANDARD, tpl.TEMPLATE_NAME)
            except KeyError:
                self.rail.set_template_info("", "")
        self._log(f"Đã mở: {path}", Colors.ACCENT_GREEN)

    def _save_session(self):
        self._sync_meta()
        path, _ = QFileDialog.getSaveFileName(self, "Lưu phiên kiểm định",
                                              "phien_kiem_dinh.json", "JSON (*.json)")
        if not path:
            return
        try:
            self._session.save_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi lưu file", str(exc)); return
        self._log(f"Đã lưu: {path}", Colors.ACCENT_GREEN)

    def _sync_meta(self):
        self._step_meta.save_to(self._session)
        self._session.meta.conclusion = self._step_export.conclusion_text()

    # -------------------------------------------------------------------------
    # Chạy bài test
    # -------------------------------------------------------------------------

    def _run_all(self):
        self._sync_meta()

        if not self.address_map:
            QMessageBox.warning(self, "Chưa kết nối thiết bị",
                                "Chưa có thiết bị nào được kết nối.\n"
                                "Bấm '🔌 Thiết bị' để quét & kết nối trước.")
            return

        enabled = [t for t in self._session.tests if t.enabled]
        if not enabled:
            QMessageBox.information(self, "Không có bài test",
                                    "Không có bài test nào được bật."); return

        missing = [t for t in enabled if not os.path.isfile(t.scenario_path)]
        if missing:
            names = "\n".join(f"  • {t.table_id}: {t.scenario_path or '(chưa chọn)'}"
                              for t in missing)
            QMessageBox.warning(self, "File kịch bản không tìm thấy",
                                f"Thiếu file cho {len(missing)} bài test:\n{names}")
            return

        for t in self._session.tests:
            t.status = "pending"; t.step_results = []
            t.result_table = None; t.error_msg = ""
        self._step_review.refresh_statuses()

        self._run_mode = "all"
        self._step_review.set_running(True)
        self._step_review.set_progress(0, len(enabled))
        self.stack.setCurrentIndex(1)
        self._current_test_index = -1
        self._run_next_test()

    def _run_one(self, index: int):
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "Đang chạy",
                                    "Đang có bài test chạy, hãy đợi xong hoặc bấm Dừng trước.")
            return
        if not self.address_map:
            QMessageBox.warning(self, "Chưa kết nối thiết bị",
                                "Chưa có thiết bị nào được kết nối.\n"
                                "Bấm '🔌 Thiết bị' để quét & kết nối trước.")
            return
        if index < 0 or index >= len(self._session.tests):
            return
        test = self._session.tests[index]
        if not os.path.isfile(test.scenario_path):
            QMessageBox.warning(self, "Thiếu file kịch bản",
                                f"Chưa chọn file kịch bản hợp lệ cho {test.table_id}.")
            return

        self._sync_meta()
        test.status = "pending"; test.step_results = []
        test.result_table = None; test.error_msg = ""
        self._step_review.refresh_row(index)

        self._run_mode = "single"
        self._current_test_index = index
        self._step_review.set_running(True)
        self._start_test(index, test)

    def _run_next_test(self):
        for i in range(self._current_test_index + 1, len(self._session.tests)):
            if self._session.tests[i].enabled:
                self._current_test_index = i
                self._start_test(i, self._session.tests[i])
                return
        self._all_tests_done()

    def _after_single_or_continue(self):
        if self._run_mode == "all":
            self._run_next_test()
        else:
            self._step_review.set_running(False)

    def _start_test(self, index: int, test: SessionTest):
        try:
            scenario = Scenario.load_json(test.scenario_path)
        except Exception as exc:  # noqa: BLE001
            test.status = "failed"; test.error_msg = str(exc)
            self._step_review.refresh_row(index)
            self._log(f"[{test.table_id}] Lỗi nạp kịch bản: {exc}", Colors.ACCENT_RED)
            self._after_single_or_continue(); return

        test.status = "running"; test.step_results = []
        self._step_results_current = []
        self._step_review.refresh_row(index)
        self._log(f"▶ Bắt đầu [{test.table_id}] {test.name}", Colors.ACCENT_PRIMARY)

        if self._run_mode == "all":
            done = sum(1 for t in self._session.tests[:index]
                       if t.status in ("done", "failed", "skipped"))
            enabled_total = sum(1 for t in self._session.tests if t.enabled)
            self._step_review.set_progress(done, enabled_total)

        self._worker = _TestWorker(scenario, self.address_map, self.cmd_delay_s)
        self._worker.result_ready.connect(self._on_step_result)
        self._worker.finished_all.connect(lambda n, idx=index: self._on_test_done(idx, n))
        self._worker.failed.connect(lambda msg, idx=index: self._on_test_failed(idx, msg))
        self._worker.start()

    def _on_step_result(self, res: StepResult):
        self._step_results_current.append(res)
        if self._current_test_index >= 0:
            self._step_review.set_live_step_count(
                self._current_test_index, len(self._step_results_current))
        win = self._scenario_win
        if win and win.isVisible() and self._current_test_index >= 0:
            running_path = self._session.tests[self._current_test_index].scenario_path
            if (win.loaded_path and running_path and
                    os.path.normcase(os.path.abspath(win.loaded_path)) ==
                    os.path.normcase(os.path.abspath(running_path))):
                win.apply_external_result(res)

    def _on_test_done(self, index: int, n_steps: int):
        test = self._session.tests[index]
        test.step_results = list(self._step_results_current)
        try:
            tpl = get_template(self._session.template_id)
            test.result_table = tpl.map_test_result(test)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[{test.table_id}] Lỗi map kết quả: {exc}", Colors.ACCENT_WARN)
        test.status = "done"
        self._step_review.refresh_row(index)
        self._log(f"✅ Xong [{test.table_id}] ({n_steps} bước)", Colors.ACCENT_GREEN)
        self._after_single_or_continue()

    def _on_test_failed(self, index: int, msg: str):
        test = self._session.tests[index]
        test.status = "failed"; test.error_msg = msg
        self._step_review.refresh_row(index)
        self._log(f"❌ Lỗi [{test.table_id}]: {msg}", Colors.ACCENT_RED)
        self._after_single_or_continue()

    def _all_tests_done(self):
        self._step_review.set_running(False)
        enabled_total = sum(1 for t in self._session.tests if t.enabled)
        self._step_review.set_progress(enabled_total, enabled_total)
        self._refresh_export_tab()
        self.stack.setCurrentIndex(2)
        passed = self._session.all_passed
        if passed is True:
            self._log("=== PHIÊN HOÀN TẤT — TẤT CẢ (ĐÃ XÁC NHẬN) ĐẠT ===", Colors.ACCENT_GREEN)
        elif passed is False:
            self._log("=== PHIÊN HOÀN TẤT — CÓ BÀI KHÔNG ĐẠT ===", Colors.ACCENT_RED)
        else:
            self._log("=== Đã chạy xong — chưa có dòng nào được xác nhận vào báo cáo ===", Colors.ACCENT_PRIMARY)

    def _stop_run(self):
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._log("Đã yêu cầu dừng...", Colors.ACCENT_WARN)

    # -------------------------------------------------------------------------
    # Xuất báo cáo
    # -------------------------------------------------------------------------

    def _open_file(self, path: str):
        try:
            os.startfile(path)  # noqa: S606 — mở bằng ứng dụng mặc định (Word) để xem/in
        except Exception as exc:  # noqa: BLE001
            self._log(f"Không tự mở được file (hãy mở thủ công): {exc}", Colors.ACCENT_WARN)

    def _export_bienban(self):
        self._sync_meta()
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu Biên Bản Kiểm Định",
            f"bien_ban_{datetime.now().strftime('%Y%m%d')}.docx",
            "Word Document (*.docx)")
        if not path:
            return
        try:
            tpl = get_template(self._session.template_id)
            tpl.generate_bienban(self._session, path)
            self._log(f"Đã xuất Biên Bản: {path}", Colors.ACCENT_GREEN)
            self._last_export_path = path
            self._step_export.set_print_enabled(True)
            self._open_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi xuất Biên Bản", str(exc))

    def _export_gcnkd(self):
        self._sync_meta()
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu Giấy Chứng Nhận Kiểm Định",
            f"gcnkd_{datetime.now().strftime('%Y%m%d')}.docx",
            "Word Document (*.docx)")
        if not path:
            return
        try:
            tpl = get_template(self._session.template_id)
            tpl.generate_gcnkd(self._session, path)
            self._log(f"Đã xuất GCN: {path}", Colors.ACCENT_GREEN)
            self._last_export_path = path
            self._step_export.set_print_enabled(True)
            self._open_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi xuất GCN", str(exc))

    def _print_last_export(self):
        if not self._last_export_path:
            QMessageBox.information(self, "Chưa có file", "Hãy xuất tài liệu trước khi in.")
            return
        try:
            os.startfile(self._last_export_path, "print")  # noqa: S606
            self._log(f"Đã gửi lệnh in: {self._last_export_path}", Colors.ACCENT_GREEN)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Lỗi in", f"Không in được: {exc}")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _refresh_export_tab(self):
        self._step_export.refresh(self._session.tests, self._session.all_passed,
                                  self._session.template_id)

    def _log(self, msg: str, color: str = Colors.TEXT_DIM):
        self.statusBar().setStyleSheet(f"color:{color};")
        self.statusBar().showMessage(msg)
        logger.info(msg)


# ============================================================================
# Entry point
# ============================================================================

def run_session_manager():
    import sys
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon("gui/logo.png"))
    app.setStyleSheet(build_global_qss())
    win = SessionManagerWindow()
    win.show()
    app.exec_()
