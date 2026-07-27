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
    QMessageBox, QTextEdit, QDateEdit, QProgressBar, QSplitter,
    QListWidget, QAbstractItemView, QCheckBox,
    QGroupBox, QScrollArea, QApplication, QFrame, QStackedWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt5.QtGui import QColor, QIcon, QPixmap

from core.session import CalibrationSession, SessionMeta, DUTInfo, SessionTest
from core.scenario import Scenario
from core.scenario_runner import ScenarioRunner, StepResult
from core.report_templates import list_templates, get_template
from gui.theme import Colors, build_global_qss
from gui.report_preview import build_wysiwyg_table

logger = logging.getLogger(__name__)

# ============================================================================
# Hằng số
# ============================================================================

STATUS_LABELS = {
    "pending":  ("⏳ Chờ",       Colors.TEXT_DIM),
    "running":  ("▶ Đang chạy",  Colors.ACCENT_CYAN),
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


def _build_rows_table(rows: list, with_checkbox: bool = False, on_toggle=None) -> QTableWidget:
    """Dựng bảng hiển thị các TableRow của 1 bài test.

    with_checkbox=True thêm cột đầu 'Đưa vào báo cáo' gắn trực tiếp vào
    TableRow.confirmed (tick/untick ghi thẳng vào object, không cần nút Lưu).
    on_toggle() được gọi mỗi khi 1 checkbox đổi trạng thái (không tham số).
    """
    tbl = QTableWidget()
    tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tbl.verticalHeader().setVisible(False)

    if not rows:
        tbl.setColumnCount(1)
        tbl.setHorizontalHeaderLabels(["Ghi chú"])
        tbl.insertRow(0)
        tbl.setItem(0, 0, QTableWidgetItem("Chưa có kết quả"))
        return tbl

    headers = ["Điểm đo", "Giá trị đo", "Đơn vị", "Sai số", "Đạt/Không"]
    offset = 0
    if with_checkbox:
        headers = ["Đưa vào\nbáo cáo"] + headers
        offset = 1

    tbl.setColumnCount(len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.setRowCount(len(rows))

    for i, r in enumerate(rows):
        if with_checkbox:
            chk = QCheckBox()
            chk.setChecked(r.confirmed)

            def _make_cb(row_obj, checkbox):
                def _cb(_state):
                    row_obj.confirmed = checkbox.isChecked()
                    if on_toggle:
                        on_toggle()
                return _cb

            chk.stateChanged.connect(_make_cb(r, chk))
            cell_w = QWidget()
            cell_lay = QHBoxLayout(cell_w)
            cell_lay.addWidget(chk)
            cell_lay.setAlignment(Qt.AlignCenter)
            cell_lay.setContentsMargins(4, 0, 4, 0)
            tbl.setCellWidget(i, 0, cell_w)

        val_str  = f"{r.value_measured:.6g}" if r.value_measured is not None else "—"
        err_str  = f"{r.error:.4e}"          if r.error is not None else "—"
        pass_str = ("✅ Đạt" if r.passed else "❌ Không đạt") if r.passed is not None else "—"
        pass_clr = (Colors.ACCENT_GREEN if r.passed else
                    (Colors.ACCENT_RED if r.passed is False else Colors.TEXT_DIM))
        for col, text in enumerate([r.key, val_str, r.value_unit, err_str, pass_str]):
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            if col == 4:
                it.setForeground(QColor(pass_clr))
            tbl.setItem(i, col + offset, it)

    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return tbl


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
        self._dots: list[QLabel] = []
        self._titles: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(0)

        for i, (title, subtitle) in enumerate(steps):
            row = QWidget()
            row.setCursor(Qt.PointingHandCursor)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(4, 8, 4, 8)
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
                line.setStyleSheet(f"background-color:{Colors.BORDER};")
                dot_col.addWidget(line, alignment=Qt.AlignHCenter)
            row_lay.addLayout(dot_col)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            t_lbl = QLabel(title)
            t_lbl.setWordWrap(True)
            s_lbl = QLabel(subtitle)
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
            text_col.addWidget(t_lbl)
            text_col.addWidget(s_lbl)
            row_lay.addLayout(text_col, 1)

            row.mousePressEvent = lambda _ev, idx=i: self.step_clicked.emit(idx)
            layout.addWidget(row)

            self._dots.append(dot)
            self._titles.append(t_lbl)

        layout.addStretch()
        self.set_current(0)

    def set_current(self, index: int):
        self._current = index
        for i, (dot, title) in enumerate(zip(self._dots, self._titles)):
            if i < index:
                dot.setText("✓")
                dot.setStyleSheet(f"font-size:14px; font-weight:bold; color:{Colors.ACCENT_GREEN};")
                title.setStyleSheet(f"color:{Colors.TEXT_MAIN}; font-size:12px;")
            elif i == index:
                dot.setText("●")
                dot.setStyleSheet(f"font-size:16px; color:{Colors.ACCENT_CYAN};")
                title.setStyleSheet(f"color:{Colors.ACCENT_CYAN}; font-size:12px; font-weight:bold;")
            else:
                dot.setText("○")
                dot.setStyleSheet(f"font-size:16px; color:{Colors.BORDER};")
                title.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:12px;")


def _pair_row(form: QFormLayout, label1: str, widget1, label2: str, widget2):
    """Đặt 2 field ngắn trên cùng 1 hàng để rút gọn chiều cao form (đỡ scroll dọc)."""
    row = QHBoxLayout()
    sub1 = QFormLayout(); sub1.setContentsMargins(0, 0, 0, 0); sub1.setSpacing(8)
    sub1.addRow(label1, widget1)
    sub2 = QFormLayout(); sub2.setContentsMargins(0, 0, 0, 0); sub2.setSpacing(8)
    sub2.addRow(label2, widget2)
    row.addLayout(sub1, 1)
    row.addLayout(sub2, 1)
    form.addRow(row)


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
        tpl_form = QFormLayout(tpl_group)
        tpl_form.setSpacing(8)
        self.cmb_template = QComboBox()
        for tid, tname in list_templates():
            self.cmb_template.addItem(tname, tid)
        tpl_form.addRow("Loại thiết bị / mẫu:", self.cmb_template)
        layout.addWidget(tpl_group)

        # --- DUT ---
        dut_group = QGroupBox("Thiết bị cần kiểm (DUT)")
        dut_form = QFormLayout(dut_group)
        dut_form.setSpacing(8)
        self.e_model  = QLineEdit()
        self.e_serial = QLineEdit()
        _pair_row(dut_form, "Model:", self.e_model, "Số serial:", self.e_serial)
        self.e_mfr    = QLineEdit()
        self.e_owner  = QLineEdit()
        _pair_row(dut_form, "Hãng sản xuất:", self.e_mfr, "Đơn vị sử dụng:", self.e_owner)
        self.e_range  = QLineEdit(); dut_form.addRow("Phạm vi đo:", self.e_range)
        layout.addWidget(dut_group)

        # --- Session meta ---
        meta_group = QGroupBox("Thông tin phiên kiểm định")
        meta_form = QFormLayout(meta_group)
        meta_form.setSpacing(8)
        self.e_operator  = QLineEdit()
        self.e_reviewer  = QLineEdit()
        _pair_row(meta_form, "Kiểm định viên:", self.e_operator, "Người soát lại:", self.e_reviewer)

        self.e_cert      = QLineEdit()
        self.e_location  = QLineEdit("Thành phố Hồ Chí Minh")
        _pair_row(meta_form, "Số GCN/BB kiểm định:", self.e_cert, "Địa điểm kiểm định:", self.e_location)

        self.e_equip     = QLineEdit(); meta_form.addRow("Phương tiện kiểm định:", self.e_equip)

        self.e_temp      = QLineEdit()
        self.e_humidity  = QLineEdit()
        _pair_row(meta_form, "Nhiệt độ:", self.e_temp, "Độ ẩm:", self.e_humidity)

        self.de_date = QDateEdit(QDate.currentDate())
        self.de_date.setCalendarPopup(True)
        self.de_date.setDisplayFormat("dd/MM/yyyy")

        self.de_valid = QDateEdit(QDate.currentDate().addYears(1))
        self.de_valid.setCalendarPopup(True)
        self.de_valid.setDisplayFormat("dd/MM/yyyy")
        _pair_row(meta_form, "Ngày kiểm định:", self.de_date, "Hiệu lực đến:", self.de_valid)

        self.e_conclusion = QLineEdit("Đạt yêu cầu kỹ thuật đo lường")
        meta_form.addRow("Kết luận:", self.e_conclusion)
        layout.addWidget(meta_group)
        layout.addStretch()

    def load_from(self, session: CalibrationSession):
        m = session.meta
        idx = self.cmb_template.findData(session.template_id)
        if idx >= 0:
            self.cmb_template.setCurrentIndex(idx)
        self.e_model.setText(m.dut.model)
        self.e_serial.setText(m.dut.serial)
        self.e_mfr.setText(m.dut.manufacturer)
        self.e_owner.setText(m.dut.owner)
        self.e_range.setText(m.dut.measurement_range)
        self.e_operator.setText(m.operator)
        self.e_reviewer.setText(m.reviewer)
        self.e_cert.setText(m.cert_number)
        self.e_equip.setText(m.inspection_equipment)
        self.e_temp.setText(m.temperature)
        self.e_humidity.setText(m.humidity)
        self.e_location.setText(m.location)
        self.e_conclusion.setText(m.conclusion)
        if m.date:
            self.de_date.setDate(QDate(m.date.year, m.date.month, m.date.day))
        if m.valid_until:
            self.de_valid.setDate(QDate(m.valid_until.year, m.valid_until.month, m.valid_until.day))

    def save_to(self, session: CalibrationSession):
        session.template_id = self.cmb_template.currentData() or ""
        m = session.meta
        m.dut.model             = self.e_model.text().strip()
        m.dut.serial            = self.e_serial.text().strip()
        m.dut.manufacturer      = self.e_mfr.text().strip()
        m.dut.owner             = self.e_owner.text().strip()
        m.dut.measurement_range = self.e_range.text().strip()
        m.operator              = self.e_operator.text().strip()
        m.reviewer              = self.e_reviewer.text().strip()
        m.cert_number           = self.e_cert.text().strip()
        m.inspection_equipment  = self.e_equip.text().strip()
        m.temperature           = self.e_temp.text().strip()
        m.humidity              = self.e_humidity.text().strip()
        m.location              = self.e_location.text().strip()
        m.conclusion            = self.e_conclusion.text().strip()
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tests: list[SessionTest] = []
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

        self.table = QTableWidget(0, len(TEST_COLS))
        self.table.setHorizontalHeaderLabels(TEST_COLS)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_CHK,    QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_TBL,    QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_NAME,   QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_FILE,   QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_CHK,    44)
        self.table.setColumnWidth(_COL_TBL,    52)
        self.table.setColumnWidth(_COL_STATUS, 160)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget::item:alternate {{ background-color: #1a1f26; }}"
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.btn_choose = QPushButton("📂 Chọn file…")
        self.btn_choose.setToolTip("Chọn file .json cho bài test đang được bôi đen")
        self.btn_choose.clicked.connect(self._choose_file_selected)
        bar.addWidget(self.btn_choose)
        bar.addStretch()
        self.btn_run = QPushButton("▶ Chạy tất cả")
        self.btn_run.setStyleSheet(
            f"background:{Colors.ACCENT_CYAN}; color:{Colors.BG_WINDOW};"
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
        self._render_result_table([])

        splitter.addWidget(right)
        splitter.setSizes([460, 700])
        layout.addWidget(splitter, 1)

    # -- Nạp / làm mới danh sách -----------------------------------------

    def load_tests(self, tests: list[SessionTest]):
        self._tests = tests
        self.table.setRowCount(0)
        for i, t in enumerate(tests):
            self._append_row(i, t)
        self._clear_detail()

    def _append_row(self, index: int, test: SessionTest):
        self.table.insertRow(index)

        chk = QCheckBox()
        chk.setChecked(test.enabled)
        chk.stateChanged.connect(lambda state, t=test: setattr(t, "enabled", state != 0))
        cell_w = QWidget()
        cell_lay = QHBoxLayout(cell_w)
        cell_lay.addWidget(chk); cell_lay.setAlignment(Qt.AlignCenter)
        cell_lay.setContentsMargins(4, 0, 4, 0)
        self.table.setCellWidget(index, _COL_CHK, cell_w)

        for col, text in [(_COL_TBL, test.table_id), (_COL_NAME, test.name)]:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(index, col, it)

        path_it = QTableWidgetItem(test.scenario_path)
        path_it.setFlags(path_it.flags() & ~Qt.ItemIsEditable)
        path_it.setForeground(QColor(Colors.TEXT_DIM if not test.scenario_path else Colors.TEXT_MAIN))
        self.table.setItem(index, _COL_FILE, path_it)

        stat_it = QTableWidgetItem("")
        stat_it.setFlags(stat_it.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(index, _COL_STATUS, stat_it)
        self._set_status_cell(index, test)

    def _set_status_cell(self, row: int, test: SessionTest):
        label, color = _test_status_label(test)
        it = self.table.item(row, _COL_STATUS)
        if it:
            it.setText(label)
            it.setForeground(QColor(color))

    def refresh_statuses(self):
        for i, t in enumerate(self._tests):
            self._set_status_cell(i, t)

    def refresh_row(self, index: int):
        if 0 <= index < len(self._tests):
            self._set_status_cell(index, self._tests[index])
            if index == self._current_index:
                self._show_test(index)

    # -- Chọn dòng / hiển thị chi tiết ------------------------------------

    def _on_selection_changed(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if rows:
            self._show_test(rows[0])

    def _clear_detail(self):
        self._current_index = None
        self.lbl_title.setText("Chọn 1 bài test bên trái để xem chi tiết")
        self.e_file.setText("")
        self.btn_run_one.setEnabled(False)
        self.btn_check_all.setEnabled(False)
        self.btn_uncheck_all.setEnabled(False)
        self._render_result_table([])

    def _show_test(self, row: int):
        if row < 0 or row >= len(self._tests):
            return
        self._current_index = row
        test = self._tests[row]
        self.lbl_title.setText(f"{test.table_id}: {test.name}")
        self.e_file.setText(test.scenario_path or "(chưa chọn file kịch bản)")
        self.btn_run_one.setEnabled(not self._running)
        rows = test.result_table.rows if test.result_table else []
        self._render_result_table(rows)
        self.btn_check_all.setEnabled(bool(rows))
        self.btn_uncheck_all.setEnabled(bool(rows))

    def _render_result_table(self, rows):
        while self._result_holder.count():
            item = self._result_holder.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        tbl = _build_rows_table(rows, with_checkbox=True, on_toggle=self._on_row_confirm_toggled)
        self._result_holder.addWidget(tbl)

    def _on_row_confirm_toggled(self):
        if self._current_index is not None and self._current_index < len(self._tests):
            self._set_status_cell(self._current_index, self._tests[self._current_index])

    def _set_all_confirmed(self, value: bool):
        if self._current_index is None:
            return
        test = self._tests[self._current_index]
        if not test.result_table:
            return
        for r in test.result_table.rows:
            r.confirmed = value
        self._render_result_table(test.result_table.rows)
        self._set_status_cell(self._current_index, test)

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
            it.setText(path)
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

class _ExportTab(QWidget):
    export_bienban_requested = pyqtSignal()
    export_gcnkd_requested   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Horizontal)

        # ── Trái: tổng hợp ────────────────────────────────────────────────
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.addWidget(QLabel("Tổng hợp các bài test:"))
        self.lst_tests = QListWidget()
        left_lay.addWidget(self.lst_tests, 1)

        self.lbl_overall = QLabel("")
        self.lbl_overall.setStyleSheet("font-weight:bold; font-size:13px;")
        left_lay.addWidget(self.lbl_overall)

        self.lbl_warning = QLabel("")
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet(f"color:{Colors.ACCENT_WARN}; font-size:11px;")
        left_lay.addWidget(self.lbl_warning)
        splitter.addWidget(left)

        # ── Phải: preview + xuất ─────────────────────────────────────────
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
        self.preview_area.setWidgetResizable(True)
        self._preview_inner = QWidget()
        self._preview_lay = QVBoxLayout(self._preview_inner)
        self._preview_lay.addWidget(QLabel("Bấm 'Xem trước' để xem nội dung sẽ đưa vào báo cáo "
                                            "(chỉ gồm các dòng đã xác nhận)."))
        self._preview_lay.addStretch()
        self.preview_area.setWidget(self._preview_inner)
        right_lay.addWidget(self.preview_area, 1)

        export_bar = QHBoxLayout()
        self.btn_bb = QPushButton("📄 Xuất & Mở Biên Bản (Phụ lục A)")
        self.btn_bb.setEnabled(False)
        self.btn_bb.clicked.connect(self.export_bienban_requested)
        export_bar.addWidget(self.btn_bb)
        self.btn_gcn = QPushButton("🏅 Xuất & Mở GCN Kiểm Định (Phụ lục B)")
        self.btn_gcn.setEnabled(False)
        self.btn_gcn.clicked.connect(self.export_gcnkd_requested)
        export_bar.addWidget(self.btn_gcn)
        right_lay.addLayout(export_bar)

        splitter.addWidget(right)
        splitter.setSizes([320, 900])
        layout.addWidget(splitter, 1)

        self._tests: list[SessionTest] = []

    def refresh(self, tests: list[SessionTest], all_passed: Optional[bool]):
        self._tests = tests
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

        if all_passed is None:
            self.lbl_overall.setText("")
            self.btn_bb.setEnabled(False)
            self.btn_gcn.setEnabled(False)
        else:
            ok = all_passed is True
            self.lbl_overall.setText("✅ TẤT CẢ (ĐÃ XÁC NHẬN) ĐẠT" if ok else "❌ CÓ BÀI KHÔNG ĐẠT")
            self.lbl_overall.setStyleSheet(
                f"font-weight:bold; font-size:13px; "
                f"color:{ Colors.ACCENT_GREEN if ok else Colors.ACCENT_RED };")
            self.btn_bb.setEnabled(True)
            self.btn_gcn.setEnabled(True)

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
                w.deleteLater()

        any_shown = False
        for t in self._tests:
            if not t.enabled or not t.result_table:
                continue
            rows = t.result_table.confirmed_rows()
            if not rows:
                continue
            any_shown = True
            title = QLabel(f"{t.table_id} — {t.name}")
            title.setStyleSheet(f"font-weight:bold; color:{Colors.ACCENT_CYAN}; font-size:12px;")
            self._preview_lay.addWidget(title)
            tbl = build_wysiwyg_table(t.table_id, rows)
            tbl.setMaximumHeight(34 * (len(rows) + 1) + 16)
            self._preview_lay.addWidget(tbl)

        if not any_shown:
            self._preview_lay.addWidget(QLabel("Chưa có dòng kết quả nào được xác nhận."))
        self._preview_lay.addStretch()


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
        mkbtn("🔧 Kịch bản", self._open_scenario_builder, Colors.ACCENT_CYAN,
              tip="Mở Scenario Builder để xây dựng / chỉnh sửa kịch bản test")
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

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = QFrame()
        log_frame.setObjectName("log_panel")
        log_lay = QVBoxLayout(log_frame)
        log_lay.setContentsMargins(12, 6, 12, 6)
        log_lay.setSpacing(4)

        log_head = QHBoxLayout()
        log_head.addWidget(QLabel("Log"))
        log_head.addStretch()
        btn_clr = QPushButton("🗑 Xóa log"); btn_clr.clicked.connect(lambda: self.log.clear())
        log_head.addWidget(btn_clr)
        log_lay.addLayout(log_head)

        self.log = QTextEdit()
        self.log.setObjectName("log_console")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        log_lay.addWidget(self.log)
        root.addWidget(log_frame)

        self.statusBar().showMessage("Sẵn sàng.")

        # Wire signals
        self._step_meta.cmb_template.currentIndexChanged.connect(self._on_template_changed)
        self._step_review.run_all_requested.connect(self._run_all)
        self._step_review.stop_requested.connect(self._stop_run)
        self._step_review.run_one_requested.connect(self._run_one)
        self._step_export.export_bienban_requested.connect(self._export_bienban)
        self._step_export.export_gcnkd_requested.connect(self._export_gcnkd)

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
        self._step_review.load_tests(self._session.tests)
        self._refresh_export_tab()

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
        self._log("Đã tạo phiên mới.", Colors.ACCENT_CYAN)

    def _load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở phiên kiểm định", "", "JSON (*.json)")
        if not path:
            return
        try:
            self._session = CalibrationSession.load_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi mở file", str(exc)); return
        self._step_meta.load_from(self._session)
        self._step_review.load_tests(self._session.tests)
        self._refresh_export_tab()
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
        self._log(f"▶ Bắt đầu [{test.table_id}] {test.name}", Colors.ACCENT_CYAN)

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
            self._log("=== Đã chạy xong — chưa có dòng nào được xác nhận vào báo cáo ===", Colors.ACCENT_CYAN)

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
            self._open_file(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi xuất GCN", str(exc))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _refresh_export_tab(self):
        self._step_export.refresh(self._session.tests, self._session.all_passed)

    def _log(self, msg: str, color: str = Colors.TEXT_DIM):
        self.log.append(f"<font color='{color}'>{msg}</font>")
        self.statusBar().showMessage(msg)


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
