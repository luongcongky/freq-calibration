"""
core/profile.py
===============
"Profile kết nối" — bản đồ thiết bị đã được gán địa chỉ VISA, do PHẦN MỀM tự
sinh ra (qua Device Manager), KHÔNG bắt user gõ tay.

Một profile gồm nhiều ProfileEntry: mỗi entry gắn một model_key (trong
DEVICE_REGISTRY) với một địa chỉ VISA cụ thể, kèm nhãn thân thiện và serial.

Profile lưu/nạp dạng JSON và quy đổi được sang address_map ({model_key: address})
để truyền thẳng cho core/scenario_runner.ScenarioRunner khi chạy REAL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from drivers import DEVICE_REGISTRY


@dataclass
class ProfileEntry:
    model_key: str
    address: str
    label: str = ""        # tên thân thiện do user đặt (vd "Máy đếm phòng A")
    serial: str = ""
    idn: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileEntry":
        return cls(
            model_key=d["model_key"],
            address=d["address"],
            label=d.get("label", ""),
            serial=d.get("serial", ""),
            idn=d.get("idn", ""),
        )


@dataclass
class ConnectionProfile:
    name: str = "Cấu hình kết nối"
    entries: list[ProfileEntry] = field(default_factory=list)

    # --- chỉnh sửa ---
    def set_entry(self, entry: ProfileEntry) -> None:
        """Thêm/ghi đè theo model_key (một model_key chỉ giữ 1 địa chỉ)."""
        for i, e in enumerate(self.entries):
            if e.model_key == entry.model_key:
                self.entries[i] = entry
                return
        self.entries.append(entry)

    def remove(self, model_key: str) -> None:
        self.entries = [e for e in self.entries if e.model_key != model_key]

    def address_map(self) -> dict[str, str]:
        """Quy đổi sang {model_key: address} cho ScenarioRunner."""
        return {e.model_key: e.address for e in self.entries}

    def warnings(self) -> list[str]:
        """Cảnh báo cấu hình (model lạ, địa chỉ trùng, model trùng nhau)."""
        out: list[str] = []
        seen_addr: dict[str, str] = {}
        seen_model: set[str] = set()
        for e in self.entries:
            if e.model_key not in DEVICE_REGISTRY:
                out.append(f"Model không có trong registry: {e.model_key}")
            if e.address in seen_addr:
                out.append(f"Địa chỉ {e.address} bị gán cho cả "
                           f"{seen_addr[e.address]} và {e.model_key}")
            seen_addr[e.address] = e.model_key
            if e.model_key in seen_model:
                out.append(f"Model {e.model_key} xuất hiện nhiều lần "
                           "(hiện chỉ giữ 1 địa chỉ mỗi model).")
            seen_model.add(e.model_key)
        return out

    # --- serialize ---
    def to_dict(self) -> dict:
        return {"name": self.name, "entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, d: dict) -> "ConnectionProfile":
        return cls(
            name=d.get("name", "Cấu hình kết nối"),
            entries=[ProfileEntry.from_dict(e) for e in d.get("entries", [])],
        )

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "ConnectionProfile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
