"""
core/scenario_runner.py
=======================
Thực thi một Scenario DẠNG CÂY (có Loop / If) trên mọi thiết bị trong
DEVICE_REGISTRY. Không phụ thuộc Qt → test được bằng pytest.

Cấu trúc thực thi (1 cấp, không lồng khối):
    - ScenarioStep : chạy action cho từng thiết bị.
    - LoopBlock    : lặp thân (các bước) N lần.
    - IfBlock      : duyệt nhánh, chạy nhánh ĐẦU TIÊN có điều kiện đúng
                     (hoặc nhánh ELSE).

Điều kiện (Condition):
    - "measure": so sánh GIÁ TRỊ ĐO gần nhất (của 1 thiết bị, hoặc bất kỳ) với ngưỡng.
    - "status" : theo TRẠNG THÁI (OK/Lỗi) của kết quả gần nhất.

Context runtime theo dõi: giá trị đo gần nhất (toàn cục + theo từng thiết bị) và
trạng thái OK/Lỗi gần nhất — để đánh giá điều kiện.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from drivers import DEVICE_REGISTRY, Reading
from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    ACTION_SPECS,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kết quả mỗi (bước, thiết bị) hoặc sự kiện điều khiển
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step_index: int = 0              # số thứ tự node cấp ngoài (1-based)
    action: str = ""
    device_key: str = ""
    ok: bool = True
    value: Optional[float] = None
    unit: str = ""
    text: str = ""
    error: str = ""
    node_id: int = 0                 # id(obj) của node/step để GUI ánh xạ
    iteration: int = 0               # vòng lặp hiện tại (0 nếu không trong loop)
    kind: str = "step"              # "step" | "control"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        tag = f"[{self.device_key}] " if self.device_key else ""
        it = f"(lần {self.iteration}) " if self.iteration else ""
        if not self.ok:
            return f"{it}{tag}{self.action}: LỖI — {self.error}"
        if self.value is not None:
            return f"{it}{tag}{self.action}: {self.value:.9g} {self.unit}"
        return f"{it}{tag}{self.action}: {self.text or 'OK'}"


ResultCallback = Callable[[StepResult], None]
StopFlag = Callable[[], bool]


# ---------------------------------------------------------------------------
# Context runtime cho điều kiện
# ---------------------------------------------------------------------------

@dataclass
class _Ctx:
    last_value: Optional[float] = None
    last_by_device: dict[str, float] = field(default_factory=dict)
    last_ok: bool = True

    def note_result(self, res: StepResult) -> None:
        if res.value is not None:
            self.last_value = res.value
            if res.device_key:
                self.last_by_device[res.device_key] = res.value
        self.last_ok = res.ok


def _compare(v: float, op: str, a: float, b: float) -> bool:
    if op == ">":
        return v > a
    if op == ">=":
        return v >= a
    if op == "<":
        return v < a
    if op == "<=":
        return v <= a
    if op == "==":
        return v == a
    lo, hi = (a, b) if a <= b else (b, a)
    if op == "between":
        return lo <= v <= hi
    if op == "outside":
        return v < lo or v > hi
    return False


def evaluate_condition(cond: Condition, ctx: _Ctx) -> tuple[bool, str]:
    """Trả (kết quả, mô tả) cho một điều kiện dựa trên context hiện tại."""
    if cond.kind == "status":
        ok = (ctx.last_ok and cond.status == "ok") or (not ctx.last_ok and cond.status == "error")
        return ok, f"trạng thái trước={'OK' if ctx.last_ok else 'LỖI'}"
    # measure
    v = ctx.last_by_device.get(cond.device) if cond.device else ctx.last_value
    if v is None:
        return False, "chưa có giá trị đo"
    res = _compare(v, cond.op, cond.value, cond.value2)
    return res, f"giá trị={v:.9g}"


# ---------------------------------------------------------------------------
# Thực thi 1 action lên 1 thiết bị
# ---------------------------------------------------------------------------

def execute_action(action: str, device, params: dict[str, Any]) -> dict:
    if action == "identify":
        return {"text": device.get_model()}
    if action == "status":
        st = device.get_status()
        bits = [f"{k}={v}" for k, v in st.items()
                if k in ("model_name", "gate_time_s", "cal_freq_hz")]
        return {"text": "; ".join(bits) or str(st)}
    if action == "set_gate_time":
        device.set_gate_time(float(params["gate_time"]))
        return {"text": f"gate={params['gate_time']}s"}
    if action == "measure_frequency":
        r: Reading = device.measure_frequency()
        return {"value": r.value, "unit": r.unit}
    if action == "set_frequency":
        device.set_frequency(float(params["freq_hz"]))
        return {"text": f"freq={params['freq_hz']}Hz"}
    if action == "zero":
        device.zero()
        return {"text": "zeroed"}
    if action == "measure_power":
        r = device.measure_power()
        return {"value": r.value, "unit": r.unit}
    if action == "wait":
        time.sleep(float(params.get("seconds", 0)))
        return {"text": f"waited {params.get('seconds', 0)}s"}
    raise ValueError(f"Action không hỗ trợ: {action}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class ScenarioRunner:
    def __init__(
        self,
        mock: bool = True,
        address_map: Optional[dict[str, str]] = None,
        on_result: Optional[ResultCallback] = None,
        stop_flag: Optional[StopFlag] = None,
        settle_wait: bool = True,
    ):
        self._mock = mock
        self._addr = address_map or {}
        self._on_result = on_result or (lambda r: None)
        self._stop_flag = stop_flag or (lambda: False)
        self._settle_wait = settle_wait
        self._results: list[StepResult] = []
        self._ctx = _Ctx()
        self._devices: dict[str, Any] = {}

    # ------------------------------------------------------------------

    def _open_device(self, device_key: str):
        cls = DEVICE_REGISTRY[device_key]["cls"]
        if self._mock:
            return cls(f"MOCK::{device_key}", mock=True)
        addr = self._addr.get(device_key)
        if not addr:
            raise ValueError(f"Chế độ real nhưng thiếu địa chỉ VISA cho '{device_key}'.")
        return cls(addr)

    def _emit(self, res: StepResult) -> None:
        self._ctx.note_result(res)
        self._results.append(res)
        self._on_result(res)

    # ------------------------------------------------------------------

    def run(self, scn: Scenario) -> list[StepResult]:
        self._results = []
        self._ctx = _Ctx()
        self._devices = {}
        try:
            for dk in scn.all_device_keys():
                self._devices[dk] = self._open_device(dk)

            for idx, node in enumerate(scn.nodes, start=1):
                if self._stop_flag():
                    log.warning("ScenarioRunner: dừng theo yêu cầu tại node %d", idx)
                    break
                if not getattr(node, "enabled", True):
                    continue
                self._run_node(idx, node)
        finally:
            for dev in self._devices.values():
                try:
                    dev.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        return self._results

    def _run_node(self, idx: int, node) -> None:
        if isinstance(node, ScenarioStep):
            self._run_step(idx, node, iteration=0)
        elif isinstance(node, LoopBlock):
            self._run_loop(idx, node)
        elif isinstance(node, IfBlock):
            self._run_if(idx, node)

    # ------------------------------------------------------------------

    def _run_loop(self, idx: int, loop: LoopBlock) -> None:
        self._emit(StepResult(step_index=idx, action="loop", kind="control",
                              node_id=id(loop), text=f"Lặp {loop.count} lần"))
        for i in range(1, loop.count + 1):
            if self._stop_flag():
                break
            for step in loop.body:
                if self._stop_flag():
                    break
                if step.enabled:
                    self._run_step(idx, step, iteration=i)

    def _run_if(self, idx: int, ib: IfBlock) -> None:
        chosen: Optional[Branch] = None
        chosen_desc = ""
        for k, br in enumerate(ib.branches, start=1):
            if not br.enabled:
                continue
            if br.condition is None:        # ELSE
                chosen, chosen_desc = br, f"nhánh {k} (ngược lại)"
                break
            ok, why = evaluate_condition(br.condition, self._ctx)
            if ok:
                chosen, chosen_desc = br, f"nhánh {k} ({br.condition.describe()}; {why})"
                break

        if chosen is None:
            self._emit(StepResult(step_index=idx, action="if", kind="control",
                                  node_id=id(ib), text="không nhánh nào khớp → bỏ qua"))
            return

        self._emit(StepResult(step_index=idx, action="if", kind="control",
                              node_id=id(ib), text=f"→ {chosen_desc}"))
        for step in chosen.body:
            if self._stop_flag():
                break
            if step.enabled:
                self._run_step(idx, step, iteration=0)

    def _run_step(self, idx: int, step: ScenarioStep, iteration: int) -> None:
        spec = ACTION_SPECS.get(step.action, {})

        if not spec.get("needs_device", True):       # wait
            res = StepResult(step_index=idx, action=step.action,
                             node_id=id(step), iteration=iteration)
            try:
                params = dict(step.params)
                if step.action == "wait" and not self._settle_wait:
                    params["seconds"] = 0
                info = execute_action(step.action, None, params)
                res.value = info.get("value"); res.unit = info.get("unit", "")
                res.text = info.get("text", "")
            except Exception as exc:  # noqa: BLE001
                res.ok = False; res.error = str(exc)
            self._emit(res)
            return

        for dk in step.devices:
            res = StepResult(step_index=idx, action=step.action, device_key=dk,
                             node_id=id(step), iteration=iteration)
            try:
                info = execute_action(step.action, self._devices[dk], step.params)
                res.value = info.get("value"); res.unit = info.get("unit", "")
                res.text = info.get("text", "")
            except Exception as exc:  # noqa: BLE001
                res.ok = False; res.error = str(exc)
            self._emit(res)
