"""
core/scenario.py
================
Mô hình "kịch bản dạng cây" cho grid step-by-step, đa thiết bị, có LUỒNG ĐIỀU KHIỂN:

  Một kịch bản gồm danh sách NODE ở cấp ngoài cùng; mỗi node là một trong:
    - ScenarioStep : một bước đơn (action trên 1..n thiết bị).
    - LoopBlock    : lặp một nhóm bước N lần.
    - IfBlock      : rẽ nhiều nhánh (IF / ELIF… / ELSE), mỗi nhánh là nhóm bước.

  Ràng buộc đợt này: KHÔNG lồng nhau — thân Loop và thân mỗi nhánh If chỉ chứa
  các bước đơn (ScenarioStep), không chứa Loop/If khác.

Điều kiện rẽ nhánh (Condition) có 2 loại:
    - "measure": so sánh GIÁ TRỊ ĐO gần nhất (của 1 thiết bị, hoặc bất kỳ) với ngưỡng.
    - "status" : theo TRẠNG THÁI bước trước (OK / Lỗi).

ACTION_SPECS chỉ là metadata cho GUI; phần thực thi nằm ở core/scenario_runner.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Union

from drivers import DEVICE_REGISTRY


# ---------------------------------------------------------------------------
# Hành động (action) — metadata cho GUI dựng form
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str           # 'float' | 'int' | 'freq_hz' | 'time_s'
    default: float
    unit: str = ""


ACTION_SPECS: dict[str, dict] = {
    "identify": {
        "label": "Nhận diện model (*IDN?)",
        "categories": ("counter", "power"), "needs_device": True, "params": [],
    },
    "status": {
        "label": "Đọc trạng thái (get_status)",
        "categories": ("counter", "power"), "needs_device": True, "params": [],
    },
    "set_gate_time": {
        "label": "Đặt gate time",
        "categories": ("counter",), "needs_device": True,
        "params": [ParamSpec("gate_time", "Gate time", "time_s", 0.1, "s")],
    },
    "measure_frequency": {
        "label": "Đo tần số",
        "categories": ("counter",), "needs_device": True, "params": [],
    },
    "set_frequency": {
        "label": "Đặt tần số (cal factor)",
        "categories": ("power",), "needs_device": True,
        "params": [ParamSpec("freq_hz", "Tần số", "freq_hz", 50e6, "Hz")],
    },
    "zero": {
        "label": "Zero đầu đo công suất",
        "categories": ("power",), "needs_device": True, "params": [],
    },
    "measure_power": {
        "label": "Đo công suất",
        "categories": ("power",), "needs_device": True, "params": [],
    },
    "wait": {
        "label": "Chờ ổn định (settle)",
        "categories": (), "needs_device": False,
        "params": [ParamSpec("seconds", "Thời gian", "time_s", 0.5, "s")],
    },
}

# Action sinh ra giá trị đo (dùng cho điều kiện "measure").
MEASURE_ACTIONS = ("measure_frequency", "measure_power")


def actions_for_category(category: str) -> list[str]:
    out = []
    for key, spec in ACTION_SPECS.items():
        if not spec["needs_device"] or category in spec["categories"]:
            out.append(key)
    return out


def actions_for_devices(device_keys: list[str]) -> list[str]:
    if not device_keys:
        return [k for k, s in ACTION_SPECS.items() if not s["needs_device"]]
    sets = []
    for dk in device_keys:
        cat = DEVICE_REGISTRY[dk]["category"]
        sets.append(set(k for k, s in ACTION_SPECS.items()
                        if s["needs_device"] and cat in s["categories"]))
    common = set.intersection(*sets) if sets else set()
    common |= {k for k, s in ACTION_SPECS.items() if not s["needs_device"]}
    return [k for k in ACTION_SPECS if k in common]


# ---------------------------------------------------------------------------
# Bước đơn
# ---------------------------------------------------------------------------

@dataclass
class ScenarioStep:
    """Một bước đơn (leaf)."""
    action: str
    devices: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    enabled: bool = True

    def describe_params(self) -> str:
        if not self.params:
            return ""
        spec_params = {p.key: p for p in ACTION_SPECS.get(self.action, {}).get("params", [])}
        bits = []
        for k, v in self.params.items():
            unit = spec_params[k].unit if k in spec_params else ""
            bits.append(f"{k}={v}{unit}")
        return ", ".join(bits)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = "step"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioStep":
        return cls(
            action=d["action"],
            devices=list(d.get("devices", [])),
            params=dict(d.get("params", {})),
            note=d.get("note", ""),
            enabled=bool(d.get("enabled", True)),
        )


# ---------------------------------------------------------------------------
# Điều kiện rẽ nhánh
# ---------------------------------------------------------------------------

OPERATORS = (">", ">=", "<", "<=", "==", "between", "outside")
OP_LABELS = {
    ">": "lớn hơn", ">=": "≥", "<": "nhỏ hơn", "<=": "≤", "==": "bằng",
    "between": "trong khoảng", "outside": "ngoài khoảng",
}


@dataclass
class Condition:
    """Điều kiện của một nhánh IF/ELIF."""
    kind: str = "measure"          # "measure" | "status"
    # --- measure ---
    device: str = ""               # model_key; "" = giá trị đo gần nhất bất kỳ
    op: str = ">"
    value: float = 0.0
    value2: float = 0.0            # cho between/outside
    # --- status ---
    status: str = "ok"             # "ok" | "error"

    def describe(self) -> str:
        if self.kind == "status":
            return f"bước trước = {'OK' if self.status == 'ok' else 'LỖI'}"
        src = self.device or "đo gần nhất"
        if self.op in ("between", "outside"):
            return f"{src} {OP_LABELS[self.op]} [{self.value}, {self.value2}]"
        return f"{src} {OP_LABELS.get(self.op, self.op)} {self.value}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        return cls(
            kind=d.get("kind", "measure"),
            device=d.get("device", ""),
            op=d.get("op", ">"),
            value=float(d.get("value", 0.0)),
            value2=float(d.get("value2", 0.0)),
            status=d.get("status", "ok"),
        )


@dataclass
class Branch:
    """Một nhánh của IfBlock. condition=None nghĩa là nhánh ELSE (ngược lại)."""
    body: list[ScenarioStep] = field(default_factory=list)
    condition: Optional[Condition] = None
    enabled: bool = True

    @property
    def is_else(self) -> bool:
        return self.condition is None

    def to_dict(self) -> dict:
        return {
            "condition": self.condition.to_dict() if self.condition else None,
            "enabled": self.enabled,
            "body": [s.to_dict() for s in self.body],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Branch":
        cond = d.get("condition")
        return cls(
            body=[ScenarioStep.from_dict(s) for s in d.get("body", [])],
            condition=Condition.from_dict(cond) if cond else None,
            enabled=bool(d.get("enabled", True)),
        )


# ---------------------------------------------------------------------------
# Khối điều khiển
# ---------------------------------------------------------------------------

@dataclass
class LoopBlock:
    """Lặp thân (chỉ gồm bước đơn) N lần."""
    count: int = 2
    body: list[ScenarioStep] = field(default_factory=list)
    note: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "type": "loop", "count": self.count, "note": self.note,
            "enabled": self.enabled, "body": [s.to_dict() for s in self.body],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LoopBlock":
        return cls(
            count=int(d.get("count", 2)),
            body=[ScenarioStep.from_dict(s) for s in d.get("body", [])],
            note=d.get("note", ""),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class IfBlock:
    """Rẽ nhiều nhánh: IF / ELIF… / ELSE."""
    branches: list[Branch] = field(default_factory=list)
    note: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "type": "if", "note": self.note, "enabled": self.enabled,
            "branches": [b.to_dict() for b in self.branches],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IfBlock":
        return cls(
            branches=[Branch.from_dict(b) for b in d.get("branches", [])],
            note=d.get("note", ""),
            enabled=bool(d.get("enabled", True)),
        )


Node = Union[ScenarioStep, LoopBlock, IfBlock]


def node_to_dict(node: Node) -> dict:
    return node.to_dict()


def node_from_dict(d: dict) -> Node:
    t = d.get("type", "step")
    if t == "loop":
        return LoopBlock.from_dict(d)
    if t == "if":
        return IfBlock.from_dict(d)
    return ScenarioStep.from_dict(d)


def node_kind(node: Node) -> str:
    if isinstance(node, LoopBlock):
        return "loop"
    if isinstance(node, IfBlock):
        return "if"
    return "step"


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str = "Kịch bản mới"
    nodes: list[Node] = field(default_factory=list)
    description: str = ""

    # --- chỉnh sửa cấp ngoài ---
    def add_node(self, node: Node, at: int | None = None) -> None:
        if at is None:
            self.nodes.append(node)
        else:
            self.nodes.insert(at, node)

    def move(self, index: int, delta: int) -> int:
        new = max(0, min(len(self.nodes) - 1, index + delta))
        if new != index:
            self.nodes.insert(new, self.nodes.pop(index))
        return new

    # --- tiện ích ---
    def iter_steps(self):
        """Duyệt mọi ScenarioStep (kể cả trong loop/if) — dùng để gom thiết bị."""
        for n in self.nodes:
            if isinstance(n, ScenarioStep):
                yield n
            elif isinstance(n, LoopBlock):
                yield from n.body
            elif isinstance(n, IfBlock):
                for b in n.branches:
                    yield from b.body

    def all_device_keys(self) -> list[str]:
        seen: list[str] = []
        for s in self.iter_steps():
            for d in s.devices:
                if d not in seen:
                    seen.append(d)
        return seen

    # --- serialize ---
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [node_to_dict(n) for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        # Back-compat: kịch bản cũ dạng phẳng {"steps": [...]}.
        if "nodes" in d:
            nodes = [node_from_dict(n) for n in d["nodes"]]
        else:
            nodes = [ScenarioStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            name=d.get("name", "Kịch bản"),
            description=d.get("description", ""),
            nodes=nodes,
        )

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load_json(cls, path: str | Path) -> "Scenario":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def _validate_step(step: ScenarioStep, where: str, problems: list[str]) -> None:
    if step.action not in ACTION_SPECS:
        problems.append(f"{where}: action không hợp lệ '{step.action}'.")
        return
    spec = ACTION_SPECS[step.action]
    for dk in step.devices:
        if dk not in DEVICE_REGISTRY:
            problems.append(f"{where}: thiết bị không có trong registry '{dk}'.")
    if spec["needs_device"] and not step.devices:
        problems.append(f"{where}: action '{step.action}' cần ít nhất 1 thiết bị.")
    for dk in step.devices:
        if dk in DEVICE_REGISTRY:
            cat = DEVICE_REGISTRY[dk]["category"]
            if spec["needs_device"] and cat not in spec["categories"]:
                problems.append(
                    f"{where}: action '{step.action}' không áp dụng cho '{dk}' "
                    f"(category={cat}).")
    for p in spec["params"]:
        if p.key not in step.params:
            problems.append(f"{where}: thiếu tham số '{p.key}' cho action '{step.action}'.")


def _validate_condition(cond: Condition, where: str, problems: list[str]) -> None:
    if cond.kind == "status":
        if cond.status not in ("ok", "error"):
            problems.append(f"{where}: trạng thái điều kiện phải là OK hoặc LỖI.")
        return
    if cond.kind == "measure":
        if cond.op not in OPERATORS:
            problems.append(f"{where}: toán tử không hợp lệ '{cond.op}'.")
        if cond.device and cond.device not in DEVICE_REGISTRY:
            problems.append(f"{where}: thiết bị điều kiện không có trong registry '{cond.device}'.")
        if cond.op in ("between", "outside") and cond.value2 == cond.value:
            problems.append(f"{where}: khoảng [{cond.value}, {cond.value2}] không hợp lệ.")
        return
    problems.append(f"{where}: loại điều kiện không hợp lệ '{cond.kind}'.")


def validate_scenario(scn: Scenario) -> list[str]:
    problems: list[str] = []
    enabled_nodes = [n for n in scn.nodes if getattr(n, "enabled", True)]
    if not enabled_nodes:
        problems.append("Kịch bản chưa có node nào được bật.")

    for i, node in enumerate(scn.nodes, start=1):
        if isinstance(node, ScenarioStep):
            _validate_step(node, f"Bước {i}", problems)
        elif isinstance(node, LoopBlock):
            if node.count < 1:
                problems.append(f"Loop {i}: số lần lặp phải ≥ 1.")
            if not node.body:
                problems.append(f"Loop {i}: chưa có bước con.")
            for j, s in enumerate(node.body, start=1):
                _validate_step(s, f"Loop {i}.{j}", problems)
        elif isinstance(node, IfBlock):
            if not node.branches:
                problems.append(f"If {i}: chưa có nhánh.")
            n_else = sum(1 for b in node.branches if b.is_else)
            if n_else > 1:
                problems.append(f"If {i}: chỉ được tối đa 1 nhánh 'ngược lại' (ELSE).")
            for k, b in enumerate(node.branches, start=1):
                if b.condition is not None:
                    _validate_condition(b.condition, f"If {i} nhánh {k}", problems)
                if not b.body:
                    problems.append(f"If {i} nhánh {k}: chưa có bước con.")
                for j, s in enumerate(b.body, start=1):
                    _validate_step(s, f"If {i} nhánh {k}.{j}", problems)
    return problems
