"""
core/session.py
===============
Model dữ liệu cho "Phiên Kiểm Định" (Calibration Session) — nhóm nhiều
kịch bản thành một lần kiểm định hoàn chỉnh, đủ dữ liệu để xuất báo cáo
theo mẫu QTKĐ.

Không phụ thuộc Qt → test được bằng pytest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Thông tin thiết bị đang kiểm (Device Under Test)
# ---------------------------------------------------------------------------

@dataclass
class DUTInfo:
    model: str = ""              # "CNT-90XL"
    serial: str = ""             # Số serial
    manufacturer: str = ""       # "Pendulum"
    owner: str = ""              # Đơn vị sử dụng
    measurement_range: str = ""  # "0,002 Hz đến 27 GHz" (từ template)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DUTInfo":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Thông tin meta của phiên kiểm định
# ---------------------------------------------------------------------------

@dataclass
class SessionMeta:
    dut: DUTInfo = field(default_factory=DUTInfo)
    operator: str = ""           # Kiểm định viên
    reviewer: str = ""           # Người soát lại
    cert_number: str = ""        # Số giấy chứng nhận
    temperature: str = ""        # "23 °C"
    humidity: str = ""           # "55 %"
    inspection_equipment: str = ""  # Phương tiện kiểm định
    date: Optional[date] = None
    valid_until: Optional[date] = None
    location: str = "Thành phố Hồ Chí Minh"
    conclusion: str = "Đạt yêu cầu kỹ thuật đo lường"

    def date_str(self) -> str:
        if self.date:
            return self.date.strftime("%d/%m/%Y")
        return ""

    def valid_until_str(self) -> str:
        if self.valid_until:
            return self.valid_until.strftime("%d/%m/%Y")
        return ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat() if self.date else None
        d["valid_until"] = self.valid_until.isoformat() if self.valid_until else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        dut = DUTInfo.from_dict(d.get("dut", {}))
        date_val = None
        if d.get("date"):
            try:
                date_val = date.fromisoformat(d["date"])
            except (ValueError, TypeError):
                pass
        valid_val = None
        if d.get("valid_until"):
            try:
                valid_val = date.fromisoformat(d["valid_until"])
            except (ValueError, TypeError):
                pass
        return cls(
            dut=dut,
            operator=d.get("operator", ""),
            reviewer=d.get("reviewer", ""),
            cert_number=d.get("cert_number", ""),
            temperature=d.get("temperature", ""),
            humidity=d.get("humidity", ""),
            inspection_equipment=d.get("inspection_equipment", ""),
            date=date_val,
            valid_until=valid_val,
            location=d.get("location", "Thành phố Hồ Chí Minh"),
            conclusion=d.get("conclusion", "Đạt yêu cầu kỹ thuật đo lường"),
        )


# ---------------------------------------------------------------------------
# Một hàng kết quả trong bảng báo cáo (TableRow)
# ---------------------------------------------------------------------------

@dataclass
class TableRow:
    """Một hàng trong bảng A1–A8 của Biên Bản Kiểm Định."""
    key: str = ""                # Nhãn hàng: "5Hz", "100kHz", "10MHz"
    freq_set: Optional[float] = None   # Tần số thiết lập (Hz)
    value_measured: Optional[float] = None  # Giá trị đo được
    value_unit: str = ""         # Đơn vị giá trị đo: "Hz", "mVrms", "dBm", "s"
    error: Optional[float] = None       # Sai số tương đối (δf / δT)
    limit: str = ""              # Sai số cho phép: "± 2,4×10⁻⁷", "≤ 15 mVrms"
    passed: Optional[bool] = None
    raw_readings: list = field(default_factory=list)  # Các lần đo riêng lẻ (cho bảng A1)
    confirmed: bool = False      # Người dùng đã rà soát & chọn đưa dòng này vào báo cáo

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TableRow":
        return cls(**{k: d.get(k, v.default if hasattr(v, 'default') else None)
                      for k, v in cls.__dataclass_fields__.items()})


# ---------------------------------------------------------------------------
# Một bảng kết quả (ReportTable = A1 đến A8)
# ---------------------------------------------------------------------------

@dataclass
class ReportTable:
    table_id: str = ""           # "A1", "A2", ..., "A8"
    name: str = ""               # "Xác định sai số tần số bộ dao động thạch anh"
    rows: list = field(default_factory=list)   # list[TableRow]
    passed: Optional[bool] = None

    def confirmed_rows(self) -> list:
        """Các dòng đã được người dùng rà soát & chọn đưa vào báo cáo."""
        return [r for r in self.rows if r.confirmed]

    @property
    def confirmed_passed(self) -> Optional[bool]:
        """None nếu chưa dòng nào được xác nhận; ngược lại đạt/không đạt
        chỉ tính trên các dòng đã xác nhận."""
        rows = self.confirmed_rows()
        if not rows:
            return None
        judged = [r for r in rows if r.passed is not None]
        if not judged:
            return None   # bảng kiểu "hiệu chuẩn" (không có đạt/không đạt)
        return all(r.passed for r in judged)

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "name": self.name,
            "rows": [r.to_dict() for r in self.rows],
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReportTable":
        return cls(
            table_id=d.get("table_id", ""),
            name=d.get("name", ""),
            rows=[TableRow.from_dict(r) for r in d.get("rows", [])],
            passed=d.get("passed"),
        )


# ---------------------------------------------------------------------------
# Một bài test trong phiên kiểm định
# ---------------------------------------------------------------------------

@dataclass
class SessionTest:
    table_id: str = ""           # "A1" → "A8"
    name: str = ""               # Tên bài test
    scenario_path: str = ""      # Đường dẫn file .json kịch bản
    enabled: bool = True
    status: str = "pending"      # "pending" | "running" | "done" | "failed" | "skipped"
    result_table: Optional[ReportTable] = None
    step_results: list = field(default_factory=list)   # list[StepResult]
    error_msg: str = ""

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "name": self.name,
            "scenario_path": self.scenario_path,
            "enabled": self.enabled,
            "status": self.status,
            "result_table": self.result_table.to_dict() if self.result_table else None,
            "error_msg": self.error_msg,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionTest":
        rt = d.get("result_table")
        return cls(
            table_id=d.get("table_id", ""),
            name=d.get("name", ""),
            scenario_path=d.get("scenario_path", ""),
            enabled=bool(d.get("enabled", True)),
            status=d.get("status", "pending"),
            result_table=ReportTable.from_dict(rt) if rt else None,
            error_msg=d.get("error_msg", ""),
        )


# ---------------------------------------------------------------------------
# Phiên kiểm định hoàn chỉnh
# ---------------------------------------------------------------------------

@dataclass
class CalibrationSession:
    meta: SessionMeta = field(default_factory=SessionMeta)
    template_id: str = ""        # "QTKD_2461_CNT90XL"
    tests: list = field(default_factory=list)   # list[SessionTest]

    @property
    def all_passed(self) -> Optional[bool]:
        """None nếu chưa có dòng nào được xác nhận; True nếu tất cả (trong số đã
        xác nhận) đạt; False nếu có ít nhất 1 không đạt. Chỉ tính trên các dòng
        kết quả đã được người dùng rà soát & xác nhận đưa vào báo cáo."""
        confirmed = [t for t in self.tests if t.enabled and t.result_table is not None
                     and t.result_table.confirmed_passed is not None]
        if not confirmed:
            return None
        return all(t.result_table.confirmed_passed for t in confirmed)

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "meta": self.meta.to_dict(),
            "tests": [t.to_dict() for t in self.tests],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationSession":
        return cls(
            meta=SessionMeta.from_dict(d.get("meta", {})),
            template_id=d.get("template_id", ""),
            tests=[SessionTest.from_dict(t) for t in d.get("tests", [])],
        )

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "CalibrationSession":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
