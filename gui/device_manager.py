"""
gui/device_manager.py
=====================
"Trình quản lý thiết bị" — giúp người KHÔNG chuyên gán địa chỉ VISA mà không
phải gõ tay. Ba cơ chế (tự động -> thủ công):

  1. 🔍 Scan & Identify : quét mọi địa chỉ VISA, tự gửi *IDN?, tự khớp driver.
  2. 🔌 Wizard cắm-từng-máy : phát hiện địa chỉ VỪA xuất hiện (cho máy đời cũ
        không có *IDN?, hoặc 2 máy trùng model).
  3. 🧪 Test mỗi dòng : mở driver thật, identify(), báo ✅/❌.

Kết quả lưu thành "profile kết nối" (JSON) -> quy đổi address_map cho
ScenarioRunner chạy REAL. Logic nằm ở core/discovery.py + core/profile.py
(đã test bằng pytest); file này chỉ là lớp GUI.
"""

from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QComboBox, QHeaderView, QFileDialog, QMessageBox,
    QAbstractItemView, QInputDialog, QSpinBox, QFrame, QWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

from drivers import DEVICE_REGISTRY
from core.discovery import (
    scan_and_identify, scan_and_identify_safe,
    snapshot_resources, diff_new_resources,
    scan_and_identify as _scan, identify_resource, match_driver,
    test_connection, DiscoveredDevice,
)
from core.profile import ConnectionProfile, ProfileEntry

logger = logging.getLogger(__name__)

from gui.theme import Colors
from gui.widgets import set_badge, paint_corner_brackets

_COL_NUM    = 0
_COL_ADDR   = 1
_COL_IDN    = 2
_COL_MATCH  = 3
_COL_ASSIGN = 4
_COL_LABEL  = 5
_COL_SERIAL = 6
_COL_TEST   = 7
_COL_STATUS = 8

DM_COLS = ["#", "Địa chỉ VISA", "*IDN?", "Nhận diện", "Gán model",
           "Tên gợi nhớ", "Serial", "Kiểm tra", "Trạng thái"]

# Danh sách model cho combo (kèm nhóm để dễ chọn).
_MODEL_ITEMS = [("", "— (không gán) —")] + [
    (k, f"{k}  ({v['vendor']}, {v['category']})") for k, v in DEVICE_REGISTRY.items()
]


class ScanWorker(QThread):
    """Quét + nhận diện ở nền — mỗi địa chỉ chạy trong subprocess riêng
    để cách ly crash NI-VISA (access violation) không làm chết app."""
    done = pyqtSignal(list)     # list[DiscoveredDevice]
    failed = pyqtSignal(str)

    def __init__(self, mock: bool, existing_profile: ConnectionProfile | None = None):
        super().__init__()
        self._mock = mock
        self._profile = existing_profile

    def run(self):
        try:
            if self._mock:
                self.done.emit(scan_and_identify(mock=True))
            else:
                self.done.emit(
                    scan_and_identify_safe(existing_profile=self._profile)
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scan failed")
            self.failed.emit(str(exc))


class DeviceManagerDialog(QDialog):
    def __init__(self, parent=None, mock: bool = True,
                 profile: ConnectionProfile | None = None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý thiết bị — gán địa chỉ VISA")
        self.setMinimumSize(1150, 680)
        self.profile = profile or ConnectionProfile()
        self._scan_worker: ScanWorker | None = None

        self._build_ui()

        self.spn_delay.setValue(int(getattr(self.profile, "cmd_delay_ms", 100)))
        if self.profile.entries:
            self._load_profile_into_table(self.profile)

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_corner_brackets(self)

    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Hướng dẫn ngắn
        tip_frame = QFrame()
        tip_frame.setStyleSheet(
            f"background:{Colors.BG_DEEP}; border-bottom:1px solid {Colors.BORDER};")
        tip_lay = QVBoxLayout(tip_frame)
        tip_lay.setContentsMargins(12, 7, 12, 7)
        tip = QLabel(
            f"Cắm thiết bị vào máy tính rồi bấm <span style='color:{Colors.ACCENT_PRIMARY};"
            f"font-weight:bold;'>Scan &amp; Identify</span> để phần mềm tự nhận diện. "
            f"Máy đời cũ không tự khai báo được? Dùng <span style='color:{Colors.ACCENT_PRIMARY};"
            f"font-weight:bold;'>Wizard cắm-từng-máy</span>."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        tip_lay.addWidget(tip)
        root.addWidget(tip_frame)

        # Hàng nút
        bar = QHBoxLayout()
        self.btn_scan = QPushButton("🔍 Scan & Identify")
        self.btn_scan.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW};"
            f" font-weight:bold; border:none; border-radius:6px; padding:8px 14px;")
        self.btn_scan.clicked.connect(self._scan)
        self.btn_wizard = QPushButton("🔌 Wizard cắm-từng-máy")
        self.btn_wizard.clicked.connect(self._wizard)
        bar.addWidget(self.btn_scan)
        bar.addWidget(self.btn_wizard)
        bar.addStretch()
        root.addLayout(bar)

        # Bảng
        self.table = QTableWidget(0, len(DM_COLS))
        self.table.setHorizontalHeaderLabels(DM_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setSectionResizeMode(_COL_NUM, QHeaderView.Fixed)
        self.table.setColumnWidth(_COL_NUM, 36)
        hdr.setSectionResizeMode(_COL_IDN, QHeaderView.Stretch)
        root.addWidget(self.table)

        # Hàng dưới: profile + xác nhận
        bottom = QHBoxLayout()
        self.btn_load = QPushButton("📂 Nạp profile")
        self.btn_load.clicked.connect(self._load_profile_file)
        self.btn_save = QPushButton("💾 Lưu profile")
        self.btn_save.clicked.connect(self._save_profile_file)
        bottom.addWidget(self.btn_load)
        bottom.addWidget(self.btn_save)
        bottom.addSpacing(16)
        bottom.addWidget(QLabel("Delay giữa lệnh (ms):"))
        self.spn_delay = QSpinBox()
        self.spn_delay.setRange(0, 60000)
        self.spn_delay.setSingleStep(10)
        self.spn_delay.setValue(100)
        self.spn_delay.setToolTip(
            "Khoảng nghỉ giữa các lệnh khi gửi tới thiết bị (0 = tắt). Lưu kèm profile."
        )
        bottom.addWidget(self.spn_delay)
        bottom.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        bottom.addWidget(self.lbl_status)
        btn_ok = QPushButton("✔ Xác nhận")
        btn_ok.setStyleSheet(
            f"background:{Colors.ACCENT_GREEN}; color:{Colors.BG_WINDOW};"
            f" font-weight:bold; border:none; border-radius:6px; padding:8px 16px;")
        btn_ok.clicked.connect(self._on_accept)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_ok)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    # Thêm dòng
    # ------------------------------------------------------------------

    @staticmethod
    def _has_idn(idn: str) -> bool:
        """Trả True nếu idn là chuỗi *IDN? thực sự (không rỗng, không phải placeholder '—')."""
        return bool(idn) and idn.strip() not in ("", "—")

    def _add_row(self, dev: DiscoveredDevice, label: str = "", assign: str | None = None):
        r = self.table.rowCount()
        self.table.insertRow(r)

        num_it = QTableWidgetItem(str(r + 1))
        num_it.setFlags(num_it.flags() & ~Qt.ItemIsEditable)
        num_it.setForeground(QColor(Colors.TEXT_DIM))
        num_it.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, _COL_NUM, num_it)

        addr_it = QTableWidgetItem(dev.address)
        addr_it.setFlags(addr_it.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, _COL_ADDR, addr_it)

        idn_w = QWidget()
        idn_lay = QHBoxLayout(idn_w)
        idn_lay.setContentsMargins(4, 1, 4, 1)
        idn_lay.setAlignment(Qt.AlignCenter)
        idn_lbl = QLabel()
        has_idn = self._has_idn(dev.idn)
        set_badge(idn_lbl, "OK" if has_idn else "—",
                 Colors.ACCENT_GREEN if has_idn else Colors.TEXT_DIM)
        idn_lbl.setToolTip(dev.idn or "")
        idn_lay.addWidget(idn_lbl)
        self.table.setCellWidget(r, _COL_IDN, idn_w)

        rec_it = QTableWidgetItem(dev.display_model())
        rec_it.setFlags(rec_it.flags() & ~Qt.ItemIsEditable)
        if dev.is_matched:
            rec_it.setForeground(QColor(Colors.ACCENT_GREEN))
        elif dev.idn:
            rec_it.setForeground(QColor(Colors.ACCENT_WARN))
        self.table.setItem(r, _COL_MATCH, rec_it)

        # combo gán model
        combo = QComboBox()
        for key, label_text in _MODEL_ITEMS:
            combo.addItem(label_text, key)
        target = assign if assign is not None else (dev.matched_key or "")
        idx = combo.findData(target)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self.table.setCellWidget(r, _COL_ASSIGN, combo)

        self.table.setItem(r, _COL_LABEL, QTableWidgetItem(label))   # Tên gợi nhớ (sửa được)
        ser_it = QTableWidgetItem(dev.serial)
        self.table.setItem(r, _COL_SERIAL, ser_it)

        # nút test
        btn = QPushButton("🧪 Test")
        btn.clicked.connect(lambda _=False, row=r: self._test_row(row))
        self.table.setCellWidget(r, _COL_TEST, btn)

        status_w = QWidget()
        status_lay = QHBoxLayout(status_w)
        status_lay.setContentsMargins(4, 1, 4, 1)
        status_lay.setAlignment(Qt.AlignCenter)
        status_lbl = QLabel()
        set_badge(status_lbl, "Chưa kiểm tra", Colors.TEXT_DIM)
        status_lay.addWidget(status_lbl)
        self.table.setCellWidget(r, _COL_STATUS, status_w)
        return r

    def _row_idn(self, r: int) -> str:
        """Đọc lại *IDN? thật (không phải chữ "OK"/"—" hiển thị trên badge) —
        lưu trong tooltip của badge lúc dựng dòng, xem _add_row()."""
        w = self.table.cellWidget(r, _COL_IDN)
        lbl = w.findChild(QLabel) if w else None
        return lbl.toolTip() if lbl else ""

    def _clear_rows(self):
        self.table.setRowCount(0)

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _scan(self):
        self.btn_scan.setEnabled(False)
        self.lbl_status.setStyleSheet(
            f"color:{Colors.ACCENT_WARN}; font-weight:bold;")
        self.lbl_status.setText("⏳ Đang quét thiết bị...")
        self._scan_worker = ScanWorker(mock=False, existing_profile=self.profile)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_done(self, devices: list):
        self.btn_scan.setEnabled(True)
        self._clear_rows()
        matched = 0
        hidden = 0
        for dev in devices:
            if not self._has_idn(dev.idn):
                hidden += 1
                continue   # ẩn thiết bị không trả *IDN? — dùng Wizard để thêm thủ công
            self._add_row(dev)
            if dev.is_matched:
                matched += 1

        # --- Tự động cập nhật & lưu profile ---
        new_prof = self._build_profile_from_table()
        if new_prof.entries:
            import os
            save_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "connection_profile.json",
            )
            try:
                new_prof.save_json(save_path)
                self.profile = new_prof
                logger.info("Auto-saved profile: %d entries → %s", len(new_prof.entries), save_path)
                auto_msg = f" | Đã tự lưu profile ({len(new_prof.entries)} thiết bị)"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-save profile thất bại: %s", exc)
                auto_msg = ""
        else:
            auto_msg = ""

        self.lbl_status.setStyleSheet(
            f"color:{Colors.ACCENT_GREEN}; font-weight:bold;")
        self.lbl_status.setText("✅ Scan hoàn tất.")

    def _on_scan_failed(self, msg: str):
        self.btn_scan.setEnabled(True)
        self.lbl_status.setStyleSheet(
            f"color:{Colors.ACCENT_RED}; font-weight:bold;")
        self.lbl_status.setText("❌ Quét thất bại.")
        QMessageBox.critical(self, "Lỗi quét", msg)

    # ------------------------------------------------------------------
    # Wizard cắm-từng-máy
    # ------------------------------------------------------------------

    def _wizard(self):
        mock = False
        QMessageBox.information(
            self, "Wizard — Bước 1/2",
            "Hãy đảm bảo thiết bị CẦN THÊM hiện CHƯA được cắm/bật.\n"
            "Nhấn OK để phần mềm ghi nhận hiện trạng."
        )
        before = snapshot_resources(mock=mock)

        # Ở mock không cắm thật được -> mô phỏng: tạm bỏ 1 địa chỉ khỏi 'before'
        # để wizard có cái "mới xuất hiện" mà demo.
        if mock and before:
            before = set(list(before)[1:])   # giả vờ địa chỉ đầu chưa cắm

        QMessageBox.information(
            self, "Wizard — Bước 2/2",
            "Bây giờ hãy cắm/bật DUY NHẤT một thiết bị.\n"
            "Nhấn OK để phát hiện thiết bị vừa xuất hiện."
        )
        after = snapshot_resources(mock=mock)
        new = diff_new_resources(before, after)

        if not new:
            QMessageBox.warning(self, "Không thấy gì mới",
                                "Chưa phát hiện địa chỉ mới. Kiểm tra cáp/nguồn rồi thử lại.")
            return
        if len(new) > 1:
            addr, ok = QInputDialog.getItem(
                self, "Nhiều thiết bị mới",
                "Phát hiện nhiều địa chỉ mới, chọn địa chỉ của máy vừa cắm:",
                new, 0, False)
            if not ok:
                return
        else:
            addr = new[0]

        # Nhận diện địa chỉ mới.
        idn = identify_resource(addr, mock=mock)
        if not self._has_idn(idn):
            QMessageBox.warning(
                self, "Thiết bị không hợp lệ",
                f"Địa chỉ {addr} không trả lời lệnh *IDN?.\n"
                "Chỉ thiết bị có phản hồi *IDN? mới được thêm vào danh sách.",
            )
            return
        dev = DiscoveredDevice(address=addr, idn=idn, matched_key=match_driver(idn),
                               serial=(idn.split(",")[2].strip() if idn.count(",") >= 2 else ""))

        # Cho user chọn model (preselect nếu đã khớp) + đặt tên.
        keys = [k for k, _ in _MODEL_ITEMS]
        labels = [lbl for _, lbl in _MODEL_ITEMS]
        preidx = keys.index(dev.matched_key) if dev.matched_key in keys else 0
        choice, ok = QInputDialog.getItem(
            self, "Gán model",
            f"Địa chỉ: {addr}\n*IDN?: {idn or '(không trả lời)'}\n\nChọn model:",
            labels, preidx, False)
        if not ok:
            return
        model_key = keys[labels.index(choice)]
        name, _ = QInputDialog.getText(self, "Tên gợi nhớ",
                                       "Đặt tên thân thiện (vd 'Máy đếm phòng A'):")
        self._add_row(dev, label=name or "", assign=model_key)
        self.lbl_status.setText(f"Đã thêm {addr} → {model_key or '(chưa gán)'}.")

    # ------------------------------------------------------------------
    # Test một dòng
    # ------------------------------------------------------------------

    def _test_row(self, r: int):
        combo: QComboBox = self.table.cellWidget(r, _COL_ASSIGN)
        model_key = combo.currentData()
        address = self.table.item(r, _COL_ADDR).text()
        if not model_key:
            self._set_status(r, "Chưa gán model", Colors.ACCENT_WARN)
            return
        res = test_connection(model_key, address, mock=False)
        if res.ok:
            self._set_status(r, f"OK: {res.model}", Colors.ACCENT_GREEN)
        else:
            self._set_status(r, f"{res.error[:40]}", Colors.ACCENT_RED, tooltip=res.error)
            if "NI-VISA" in res.error:
                QMessageBox.warning(self, "Thiếu driver NI-VISA", res.error)

    def _set_status(self, r: int, text: str, color: str, tooltip: str = ""):
        w = self.table.cellWidget(r, _COL_STATUS)
        lbl = w.findChild(QLabel) if w else None
        if lbl is None:
            return
        set_badge(lbl, text, color)
        if tooltip:
            lbl.setToolTip(tooltip)

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def _build_profile_from_table(self) -> ConnectionProfile:
        prof = ConnectionProfile(name=self.profile.name,
                                 cmd_delay_ms=int(self.spn_delay.value()))
        for r in range(self.table.rowCount()):
            combo: QComboBox = self.table.cellWidget(r, _COL_ASSIGN)
            model_key = combo.currentData()
            if not model_key:
                continue
            prof.set_entry(ProfileEntry(
                model_key=model_key,
                address=self.table.item(r, _COL_ADDR).text(),
                label=(self.table.item(r, _COL_LABEL).text() if self.table.item(r, _COL_LABEL) else ""),
                serial=(self.table.item(r, _COL_SERIAL).text() if self.table.item(r, _COL_SERIAL) else ""),
                idn=self._row_idn(r),
            ))
        return prof

    def _load_profile_into_table(self, prof: ConnectionProfile):
        self._clear_rows()
        self.spn_delay.setValue(int(getattr(prof, "cmd_delay_ms", 100)))
        hidden = 0
        for e in prof.entries:
            if not self._has_idn(e.idn):
                hidden += 1
                continue   # ẩn thiết bị không có *IDN? — dùng Wizard để thêm
            dev = DiscoveredDevice(address=e.address, idn=e.idn,
                                   matched_key=e.model_key, serial=e.serial)
            self._add_row(dev, label=e.label, assign=e.model_key)
        if hidden:
            logger.info("_load_profile_into_table: ẩn %d thiết bị không có *IDN?", hidden)

    def _save_profile_file(self):
        prof = self._build_profile_from_table()
        if not prof.entries:
            QMessageBox.warning(self, "Trống", "Chưa có thiết bị nào được gán model.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu profile", "connection_profile.json",
                                              "JSON (*.json)")
        if not path:
            return
        prof.save_json(path)
        self.profile = prof
        self.lbl_status.setText(f"Đã lưu profile: {path}")

    def _load_profile_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Nạp profile", "", "JSON (*.json)")
        if not path:
            return
        try:
            prof = ConnectionProfile.load_json(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Lỗi nạp profile", str(exc))
            return
        self.profile = prof
        self._load_profile_into_table(prof)
        self.lbl_status.setText(f"Đã nạp profile: {path}")

    # ------------------------------------------------------------------

    def _on_accept(self):
        prof = self._build_profile_from_table()
        warns = prof.warnings()
        if warns:
            ret = QMessageBox.question(
                self, "Cảnh báo cấu hình",
                "\n".join(warns) + "\n\nVẫn áp dụng?",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.profile = prof
        self.accept()

    def get_profile(self) -> ConnectionProfile:
        return self.profile

    def is_mock(self) -> bool:
        return False
