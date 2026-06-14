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

import re
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Union

from drivers import DEVICE_REGISTRY
from core.expr import validate as _expr_validate, ExprError


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
        "categories": ("counter", "power", "generator"), "needs_device": True, "params": [],
    },
    "status": {
        "label": "Đọc trạng thái (get_status)",
        "categories": ("counter", "power", "generator"), "needs_device": True, "params": [],
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
        "label": "Đặt tần số (cal factor — power meter)",
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
    # --- Generator (SMW200A) ---
    "set_rf_frequency": {
        "label": "Đặt tần số RF (generator)",
        "categories": ("generator",), "needs_device": True,
        "params": [ParamSpec("freq_hz", "Tần số RF", "freq_hz", 1e9, "Hz")],
    },
    "set_rf_power": {
        "label": "Đặt công suất RF (generator)",
        "categories": ("generator",), "needs_device": True,
        "params": [ParamSpec("power_dbm", "Công suất", "power_dbm", -10.0, "dBm")],
    },
    "rf_on": {
        "label": "Bật RF output",
        "categories": ("generator",), "needs_device": True, "params": [],
    },
    "rf_off": {
        "label": "Tắt RF output",
        "categories": ("generator",), "needs_device": True, "params": [],
    },
    "wait": {
        "label": "Chờ ổn định (settle)",
        "categories": (), "needs_device": False,
        "params": [ParamSpec("seconds", "Thời gian", "time_s", 0.5, "s")],
    },
    # --- Biến / Tính toán (Phase 2) — params tự do (name/expr), không dùng ParamSpec ---
    "set_var": {
        "label": "Gán biến (= biểu thức)",
        "categories": (), "needs_device": False, "params": [],
    },
    "compute": {
        "label": "Tính toán → biến",
        "categories": (), "needs_device": False, "params": [],
    },
    "collect": {
        "label": "Thu thập vào list",
        "categories": (), "needs_device": False, "params": [],
    },
    "break": {
        "label": "⛔ Thoát vòng lặp (break)",
        "categories": (), "needs_device": False, "params": [],
        "desc": "Dừng vòng lặp Loop đang chạy ngay lập tức",
    },
    "label": {
        "label": "◆ Điểm thao tác (label)",
        "categories": (), "needs_device": False, "params": [],
        "desc": "Đánh dấu một điểm để goto nhảy tới",
    },
    "goto": {
        "label": "→ Nhảy tới điểm (goto)",
        "categories": (), "needs_device": False, "params": [],
        "desc": "Nhảy tới điểm thao tác (label) cùng tên",
    },
}

# Action thao tác trên biến (không gọi thiết bị, không cần ParamSpec).
VAR_ACTIONS = ("set_var", "compute", "collect")

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
        if self.action == "raw_scpi":
            template = self.params.get("__template__", "")
            sub = {k: v for k, v in self.params.items() if not k.startswith("__")}
            try:
                return template.format(**sub)
            except (KeyError, ValueError):
                return template
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
    kind: str = "measure"          # "measure" | "status" | "expr"
    # --- measure ---
    device: str = ""               # model_key; "" = giá trị đo gần nhất bất kỳ
    op: str = ">"
    value: float = 0.0
    value2: float = 0.0            # cho between/outside
    # --- status ---
    status: str = "ok"             # "ok" | "error"
    # --- expr (Phase 2): so sánh kết quả biểu thức (trên biến) với value ---
    expr: str = ""                 # vd "error"  -> so eval(expr) với value/value2

    def describe(self) -> str:
        if self.kind == "status":
            return f"bước trước = {'OK' if self.status == 'ok' else 'LỖI'}"
        src = self.expr if self.kind == "expr" else (self.device or "đo gần nhất")
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
            expr=d.get("expr", ""),
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
            body=[node_from_dict(s) for s in d.get("body", [])],   # nhánh lồng được Loop/If
            condition=Condition.from_dict(cond) if cond else None,
            enabled=bool(d.get("enabled", True)),
        )


# ---------------------------------------------------------------------------
# Khối điều khiển
# ---------------------------------------------------------------------------

@dataclass
class LoopBlock:
    """Lặp thân. mode='count': lặp N lần. mode='until': lặp tới khi điều kiện
    dừng đúng (do-until), chặn bởi max_iter. Thân CÓ THỂ chứa Loop/If lồng nhau."""
    count: int = 2
    body: list = field(default_factory=list)            # list[Node]
    note: str = ""
    enabled: bool = True
    mode: str = "count"                                 # "count" | "until"
    condition: Optional["Condition"] = None             # điều kiện DỪNG khi mode="until"
    max_iter: int = 50                                  # trần an toàn cho until

    def to_dict(self) -> dict:
        return {
            "type": "loop", "count": self.count, "note": self.note,
            "enabled": self.enabled, "mode": self.mode, "max_iter": self.max_iter,
            "condition": self.condition.to_dict() if self.condition else None,
            "body": [n.to_dict() for n in self.body],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LoopBlock":
        cond = d.get("condition")
        return cls(
            count=int(d.get("count", 2)),
            body=[node_from_dict(s) for s in d.get("body", [])],   # node_from_dict -> lồng được
            note=d.get("note", ""),
            enabled=bool(d.get("enabled", True)),
            mode=d.get("mode", "count"),
            condition=Condition.from_dict(cond) if cond else None,
            max_iter=int(d.get("max_iter", 50)),
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
        """Duyệt mọi ScenarioStep (kể cả trong loop/if LỒNG NHAU) — gom thiết bị."""
        def walk(nodes):
            for n in nodes:
                if isinstance(n, ScenarioStep):
                    yield n
                elif isinstance(n, LoopBlock):
                    yield from walk(n.body)
                elif isinstance(n, IfBlock):
                    for b in n.branches:
                        yield from walk(b.body)
        yield from walk(self.nodes)

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

def _check_expr(expr: str, where: str, problems: list[str]) -> None:
    try:
        _expr_validate(expr)
    except ExprError as e:
        problems.append(f"{where}: biểu thức lỗi — {e}")


def _validate_step(step: ScenarioStep, where: str, problems: list[str]) -> None:
    if step.action in ("set_var", "compute"):
        if not (step.params.get("name") or step.params.get("target")):
            problems.append(f"{where}: {step.action} thiếu tên biến (name).")
        expr = step.params.get("expr", "")
        if not expr:
            problems.append(f"{where}: {step.action} thiếu biểu thức (expr).")
        else:
            _check_expr(expr, where, problems)
        return
    if step.action == "collect":
        if not step.params.get("var"):
            problems.append(f"{where}: collect thiếu tên list (var).")
        _check_expr(step.params.get("source", "$last"), where, problems)
        return

    if step.action == "raw_scpi":
        if not step.devices:
            problems.append(f"{where}: lệnh SCPI cần ít nhất 1 thiết bị.")
        for dk in step.devices:
            if dk not in DEVICE_REGISTRY:
                problems.append(f"{where}: thiết bị không có trong registry '{dk}'.")
        # tham số dạng '=biểu_thức' phải parse được.
        for k, v in step.params.items():
            if isinstance(v, str) and v.startswith("=") and not k.startswith("__"):
                _check_expr(v[1:], f"{where} (tham số '{k}')", problems)
        template = step.params.get("__template__", "")
        # #4: mọi placeholder {name} trong lệnh phải có giá trị tương ứng trong params.
        provided = {k for k in step.params if not k.startswith("__")}
        placeholders = set(re.findall(r"\{([A-Za-z_]\w*)\}", template))
        missing = placeholders - provided
        if missing:
            problems.append(f"{where}: lệnh SCPI thiếu giá trị tham số: "
                            f"{', '.join(sorted(missing))}.")
        # #3: có '?' nhưng chưa đánh dấu là truy vấn → kết quả sẽ không được đọc.
        if "?" in template and not step.params.get("__is_query__", False):
            problems.append(f"{where}: lệnh '{template}' có '?' nhưng chưa đánh dấu là "
                            f"truy vấn (query) — kết quả trả về sẽ không được đọc về.")
        return
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
    if cond.kind == "expr":
        if cond.op not in OPERATORS:
            problems.append(f"{where}: toán tử không hợp lệ '{cond.op}'.")
        if not cond.expr:
            problems.append(f"{where}: điều kiện biểu thức thiếu expr.")
        else:
            _check_expr(cond.expr, where, problems)
        if cond.op in ("between", "outside") and cond.value2 == cond.value:
            problems.append(f"{where}: khoảng [{cond.value}, {cond.value2}] không hợp lệ.")
        return
    problems.append(f"{where}: loại điều kiện không hợp lệ '{cond.kind}'.")


MAX_NEST_DEPTH = 4      # độ sâu lồng khối tối đa (an toàn / tránh rối)


def _validate_node(node, where: str, problems: list[str], depth: int) -> None:
    if isinstance(node, ScenarioStep):
        _validate_step(node, where, problems)
        return
    if depth > MAX_NEST_DEPTH:
        problems.append(f"{where}: lồng khối quá sâu (> {MAX_NEST_DEPTH} cấp).")
        return
    if isinstance(node, LoopBlock):
        if node.mode == "until":
            if node.condition is None:
                problems.append(f"{where}: Loop 'đến khi' cần điều kiện dừng.")
            else:
                _validate_condition(node.condition, f"{where} (điều kiện dừng)", problems)
            if node.max_iter < 1:
                problems.append(f"{where}: max_iter phải ≥ 1.")
        elif node.count < 1:
            problems.append(f"{where}: số lần lặp phải ≥ 1.")
        if not node.body:
            problems.append(f"{where}: chưa có bước con.")
        for j, s in enumerate(node.body, start=1):
            _validate_node(s, f"{where}.{j}", problems, depth + 1)
    elif isinstance(node, IfBlock):
        if not node.branches:
            problems.append(f"{where}: chưa có nhánh.")
        if sum(1 for b in node.branches if b.is_else) > 1:
            problems.append(f"{where}: chỉ được tối đa 1 nhánh 'ngược lại' (ELSE).")
        for k, b in enumerate(node.branches, start=1):
            if b.condition is not None:
                _validate_condition(b.condition, f"{where} nhánh {k}", problems)
            if not b.body:
                problems.append(f"{where} nhánh {k}: chưa có bước con.")
            for j, s in enumerate(b.body, start=1):
                _validate_node(s, f"{where} nhánh {k}.{j}", problems, depth + 1)


def validate_scenario(scn: Scenario) -> list[str]:
    problems: list[str] = []
    enabled_nodes = [n for n in scn.nodes if getattr(n, "enabled", True)]
    if not enabled_nodes:
        problems.append("Kịch bản chưa có node nào được bật.")
    for i, node in enumerate(scn.nodes, start=1):
        label = {"step": "Bước", "loop": "Loop", "if": "If"}[node_kind(node)]
        _validate_node(node, f"{label} {i}", problems, depth=1)

    # --- Nhãn (label) cấp ngoài cùng + đích goto ---
    top_labels: dict[str, int] = {}
    for n in scn.nodes:
        if isinstance(n, ScenarioStep) and n.action == "label":
            nm = n.params.get("name", "")
            if not nm:
                problems.append("Label: thiếu tên điểm thao tác.")
            elif nm in top_labels:
                problems.append(f"Label: tên '{nm}' bị trùng (mỗi điểm phải duy nhất).")
            else:
                top_labels[nm] = 1
    for step in scn.iter_steps():        # goto có thể nằm trong Loop/If -> duyệt đệ quy
        if step.action == "goto":
            tgt = step.params.get("target", "")
            if not tgt:
                problems.append("Goto: chưa chọn điểm thao tác đích.")
            elif tgt not in top_labels:
                problems.append(f"Goto: điểm thao tác '{tgt}' không tồn tại ở cấp ngoài cùng.")
    return problems
