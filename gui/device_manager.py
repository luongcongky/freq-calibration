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
    QCheckBox, QAbstractItemView, QInputDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from drivers import DEVICE_REGISTRY
from core.discovery import (
    scan_and_identify, snapshot_resources, diff_new_resources,
    scan_and_identify as _scan, identify_resource, match_driver,
    test_connection, DiscoveredDevice,
)
from core.profile import ConnectionProfile, ProfileEntry

logger = logging.getLogger(__name__)

from gui.theme import Colors


DM_COLS = ["Địa chỉ VISA", "*IDN?", "Nhận diện", "Gán model",
           "Tên gợi nhớ", "Serial", "Kiểm tra", "Trạng thái"]

# Danh sách model cho combo (kèm nhóm để dễ chọn).
_MODEL_ITEMS = [("", "— (không gán) —")] + [
    (k, f"{k}  ({v['vendor']}, {v['category']})") for k, v in DEVICE_REGISTRY.items()
]


class ScanWorker(QThread):
    """Quét + nhận diện ở nền (tránh treo UI khi scan GPIB/LAN thật)."""
    done = pyqtSignal(list)     # list[DiscoveredDevice]
    failed = pyqtSignal(str)

    def __init__(self, mock: bool):
        super().__init__()
        self._mock = mock

    def run(self):
        try:
            self.done.emit(scan_and_identify(mock=self._mock))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scan failed")
            self.failed.emit(str(exc))


class DeviceManagerDialog(QDialog):
    def __init__(self, parent=None, mock: bool = True,
                 profile: ConnectionProfile | None = None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý thiết bị — gán địa chỉ VISA")
        self.setMinimumSize(980, 560)
        self.profile = profile or ConnectionProfile()
        self._scan_worker: ScanWorker | None = None

        self.setStyleSheet(
            f"QDialog {{ background:{Colors.BG_WINDOW}; color:{Colors.TEXT_MAIN};"
            f" font-family:'Segoe UI'; }}"
            f"QLabel {{ color:{Colors.TEXT_MAIN}; }}"
            f"QPushButton {{ background:{Colors.BG_CARD}; border:1px solid {Colors.BORDER};"
            f" border-radius:6px; padding:7px 12px; }}"
            f"QPushButton:hover {{ border-color:{Colors.ACCENT_CYAN}; }}"
            f"QTableWidget {{ background:{Colors.BG_INPUT}; gridline-color:{Colors.BORDER};"
            f" border:1px solid {Colors.BORDER}; }}"
            f"QHeaderView::section {{ background:{Colors.BG_CARD}; color:{Colors.TEXT_DIM};"
            f" border:none; border-bottom:2px solid {Colors.BORDER}; padding:7px; }}"
            f"QComboBox, QLineEdit {{ background:{Colors.BG_CARD}; color:{Colors.TEXT_MAIN};"
            f" border:1px solid {Colors.BORDER}; border-radius:4px; padding:4px; }}"
        )
        self._build_ui()

        # Mặc định mock theo tham số.
        self.chk_mock.setChecked(mock)
        if self.profile.entries:
            self._load_profile_into_table(self.profile)

    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Hướng dẫn ngắn
        tip = QLabel(
            "Cắm thiết bị vào máy tính rồi bấm <b>Scan &amp; Identify</b> để phần mềm "
            "tự nhận diện. Máy đời cũ không tự khai báo được? Dùng "
            "<b>Wizard cắm-từng-máy</b>."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        root.addWidget(tip)

        # Hàng nút
        bar = QHBoxLayout()
        self.btn_scan = QPushButton("🔍 Scan & Identify")
        self.btn_scan.setStyleSheet(
            f"background:{Colors.ACCENT_CYAN}; color:{Colors.BG_WINDOW};"
            f" font-weight:bold; border:none; border-radius:6px; padding:8px 14px;")
        self.btn_scan.clicked.connect(self._scan)
        self.btn_wizard = QPushButton("🔌 Wizard cắm-từng-máy")
        self.btn_wizard.clicked.connect(self._wizard)
        bar.addWidget(self.btn_scan)
        bar.addWidget(self.btn_wizard)
        bar.addStretch()
        self.chk_mock = QCheckBox("MOCK (demo, không cần phần cứng)")
        self.chk_mock.setChecked(True)
        bar.addWidget(self.chk_mock)
        root.addLayout(bar)

        # Bảng
        self.table = QTableWidget(0, len(DM_COLS))
        self.table.setHorizontalHeaderLabels(DM_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)   # *IDN?
        root.addWidget(self.table)

        # Hàng dưới: profile + xác nhận
        bottom = QHBoxLayout()
        self.btn_load = QPushButton("📂 Nạp profile")
        self.btn_load.clicked.connect(self._load_profile_file)
        self.btn_save = QPushButton("💾 Lưu profile")
        self.btn_save.clicked.connect(self._save_profile_file)
        bottom.addWidget(self.btn_load)
        bottom.addWidget(self.btn_save)
        bottom.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color:{Colors.TEXT_DIM};")
        bottom.addWidget(self.lbl_status)
        btn_ok = QPushButton("✔ Áp dụng")
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

    def _add_row(self, dev: DiscoveredDevice, label: str = "", assign: str | None = None):
        r = self.table.rowCount()
        self.table.insertRow(r)

        addr_it = QTableWidgetItem(dev.address)
        addr_it.setFlags(addr_it.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 0, addr_it)

        idn_it = QTableWidgetItem(dev.idn or "—")
        idn_it.setFlags(idn_it.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 1, idn_it)

        rec_it = QTableWidgetItem(dev.display_model())
        rec_it.setFlags(rec_it.flags() & ~Qt.ItemIsEditable)
        if dev.is_matched:
            rec_it.setForeground(Qt.green)
        elif dev.idn:
            rec_it.setForeground(Qt.yellow)
        self.table.setItem(r, 2, rec_it)

        # combo gán model
        combo = QComboBox()
        for key, label_text in _MODEL_ITEMS:
            combo.addItem(label_text, key)
        target = assign if assign is not None else (dev.matched_key or "")
        idx = combo.findData(target)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self.table.setCellWidget(r, 3, combo)

        self.table.setItem(r, 4, QTableWidgetItem(label))           # Tên gợi nhớ (sửa được)
        ser_it = QTableWidgetItem(dev.serial)
        self.table.setItem(r, 5, ser_it)

        # nút test
        btn = QPushButton("🧪 Test")
        btn.clicked.connect(lambda _=False, row=r: self._test_row(row))
        self.table.setCellWidget(r, 6, btn)

        self.table.setItem(r, 7, QTableWidgetItem(""))
        return r

    def _clear_rows(self):
        self.table.setRowCount(0)

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _scan(self):
        self.btn_scan.setEnabled(False)
        self.lbl_status.setText("Đang quét & nhận diện...")
        self._scan_worker = ScanWorker(mock=self.chk_mock.isChecked())
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_done(self, devices: list):
        self.btn_scan.setEnabled(True)
        self._clear_rows()
        matched = 0
        for dev in devices:
            self._add_row(dev)
            if dev.is_matched:
                matched += 1
        self.lbl_status.setText(
            f"Tìm thấy {len(devices)} thiết bị, tự nhận diện {matched}. "
            f"Máy chưa khớp: chọn model thủ công hoặc dùng Wizard."
        )

    def _on_scan_failed(self, msg: str):
        self.btn_scan.setEnabled(True)
        self.lbl_status.setText("Quét lỗi.")
        QMessageBox.critical(self, "Lỗi quét", msg)

    # ------------------------------------------------------------------
    # Wizard cắm-từng-máy
    # ------------------------------------------------------------------

    def _wizard(self):
        mock = self.chk_mock.isChecked()
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
        combo: QComboBox = self.table.cellWidget(r, 3)
        model_key = combo.currentData()
        address = self.table.item(r, 0).text()
        if not model_key:
            self._set_status(r, "Chưa gán model", Colors.ACCENT_WARN)
            return
        res = test_connection(model_key, address, mock=self.chk_mock.isChecked())
        if res.ok:
            self._set_status(r, f"✅ OK: {res.model}", Colors.ACCENT_GREEN)
        else:
            self._set_status(r, f"❌ {res.error[:40]}", Colors.ACCENT_RED)

    def _set_status(self, r: int, text: str, color: str):
        it = QTableWidgetItem(text)
        it.setForeground(Qt.green if color == Colors.ACCENT_GREEN
                         else (Qt.red if color == Colors.ACCENT_RED else Qt.yellow))
        self.table.setItem(r, 7, it)

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def _build_profile_from_table(self) -> ConnectionProfile:
        prof = ConnectionProfile(name=self.profile.name)
        for r in range(self.table.rowCount()):
            combo: QComboBox = self.table.cellWidget(r, 3)
            model_key = combo.currentData()
            if not model_key:
                continue
            prof.set_entry(ProfileEntry(
                model_key=model_key,
                address=self.table.item(r, 0).text(),
                label=(self.table.item(r, 4).text() if self.table.item(r, 4) else ""),
                serial=(self.table.item(r, 5).text() if self.table.item(r, 5) else ""),
                idn=(self.table.item(r, 1).text() if self.table.item(r, 1) else ""),
            ))
        return prof

    def _load_profile_into_table(self, prof: ConnectionProfile):
        self._clear_rows()
        for e in prof.entries:
            dev = DiscoveredDevice(address=e.address, idn=e.idn,
                                   matched_key=e.model_key, serial=e.serial)
            self._add_row(dev, label=e.label, assign=e.model_key)

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
        return self.chk_mock.isChecked()
