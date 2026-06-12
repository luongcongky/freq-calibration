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
from core.expr import evaluate as eval_expr, ExprError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Định dạng số kiểu Việt Nam (nhóm nghìn '.', thập phân ',') — KHÔNG dùng ký
# pháp khoa học. Ví dụ: 1e11 -> "100.000.000.000", -10.5 -> "-10,5".
# Chỉ dùng để HIỂN THỊ; giá trị tính toán (so sánh điều kiện) vẫn là float.
# ---------------------------------------------------------------------------

def format_number_vi(v: float, max_frac: int = 9) -> str:
    if v != v or v in (float("inf"), float("-inf")):   # NaN / vô cực
        return str(v)
    neg = v < 0
    a = abs(v)
    if a == int(a):                                    # số nguyên (vd tần số Hz)
        body = f"{int(a):,}".replace(",", ".")
    else:                                              # có phần thập phân
        s = f"{a:,.{max_frac}f}".rstrip("0").rstrip(".")   # ',' = nghìn, '.' = thập phân
        int_str, _, frac_str = s.partition(".")
        int_str = int_str.replace(",", ".")
        body = f"{int_str},{frac_str}" if frac_str else int_str
    return f"-{body}" if neg else body


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
    is_query: bool = False           # raw_scpi: lệnh truy vấn (có đọc kết quả về)
    node_id: int = 0                 # id(obj) của node/step để GUI ánh xạ
    iteration: int = 0               # vòng lặp hiện tại (0 nếu không trong loop)
    kind: str = "step"              # "step" | "control"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        """Chuỗi ĐẦY ĐỦ cho LOG (kèm thiết bị + action + vòng lặp)."""
        tag = f"[{self.device_key}] " if self.device_key else ""
        it = f"(lần {self.iteration}) " if self.iteration else ""
        if not self.ok:
            return f"{it}{tag}{self.action}: LỖI — {self.error}"
        if self.value is not None:
            return f"{it}{tag}{self.action}: {format_number_vi(self.value)} {self.unit}"
        return f"{it}{tag}{self.action}: {self.text or 'OK'}"

    def result_cell(self) -> str:
        """Chuỗi cho cột 'Kết quả' trên grid — chỉ hiện thông tin CÓ NGHĨA, không
        lặp [thiết bị]/action và không trùng cột Trạng thái.
          - lỗi      → chi tiết lỗi (cột Trạng thái chỉ báo cờ LỖI)
          - lệnh đọc → giá trị / chuỗi đọc được
          - lệnh ghi → TRỐNG (thành công đã thể hiện ở cột Trạng thái)."""
        if not self.ok:
            return f"LỖI — {self.error}" if self.error else "LỖI"
        if self.action in ("set_var", "compute", "collect"):   # biến: hiện giá trị gán
            return self.text
        if self.value is not None:                      # query trả về SỐ
            return f"{format_number_vi(self.value)} {self.unit}".rstrip()
        if self.is_query:                               # query trả về chuỗi (vd 'INT', 'ON')
            return self.text
        return ""                                       # lệnh ghi: để trống


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
    variables: dict[str, Any] = field(default_factory=dict)   # biến do set_var/compute/collect tạo
    iter_stack: list[int] = field(default_factory=list)       # chỉ số vòng lặp lồng nhau

    def note_result(self, res: StepResult) -> None:
        if res.value is not None:
            self.last_value = res.value
            if res.device_key:
                self.last_by_device[res.device_key] = res.value
        self.last_ok = res.ok

    def eval_env(self) -> dict:
        """Môi trường cho biểu thức: biến + $last (giá trị đo gần nhất) + $iter
        (chỉ số vòng lặp trong cùng đang chạy)."""
        env = dict(self.variables)
        env["$last"] = self.last_value if self.last_value is not None else 0.0
        if self.iter_stack:
            env["$iter"] = self.iter_stack[-1]
        return env


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
    if cond.kind == "expr":
        try:
            v = eval_expr(cond.expr, ctx.eval_env())
        except ExprError as e:
            return False, f"lỗi biểu thức: {e}"
        return _compare(v, cond.op, cond.value, cond.value2), f"{cond.expr}={format_number_vi(v)}"
    # measure
    v = ctx.last_by_device.get(cond.device) if cond.device else ctx.last_value
    if v is None:
        return False, "chưa có giá trị đo"
    res = _compare(v, cond.op, cond.value, cond.value2)
    return res, f"giá trị={format_number_vi(v)}"


# ---------------------------------------------------------------------------
# Thực thi 1 action lên 1 thiết bị
# ---------------------------------------------------------------------------

def _parse_leading_float(resp: str) -> Optional[float]:
    """Thử lấy SỐ (float) ở đầu chuỗi trả lời SCPI; None nếu không phải số.

    Hỗ trợ các dạng phổ biến: '1.2345E9', '1.2345E9 HZ' (kèm đơn vị),
    '-10.0,...' (lấy phần tử đầu trước dấu phẩy), '+1.0E+02'.
    Trả None cho chuỗi trạng thái như 'ON', 'INT' → khi đó chỉ giữ text.
    """
    if not resp:
        return None
    head = resp.strip().split(",")[0].split()[0] if resp.strip() else ""
    try:
        return float(head)
    except ValueError:
        return None


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
    if action == "set_rf_frequency":
        device.set_frequency(float(params["freq_hz"]))
        return {"text": f"RF freq={params['freq_hz']}Hz"}
    if action == "set_rf_power":
        device.set_power(float(params["power_dbm"]))
        return {"text": f"RF power={params['power_dbm']}dBm"}
    if action == "rf_on":
        device.rf_on()
        return {"text": "RF output ON"}
    if action == "rf_off":
        device.rf_off()
        return {"text": "RF output OFF"}
    if action == "wait":
        time.sleep(float(params.get("seconds", 0)))
        return {"text": f"waited {params.get('seconds', 0)}s"}
    if action == "raw_scpi":
        template = params.get("__template__", "")
        is_query = bool(params.get("__is_query__", False))
        sub = {k: v for k, v in params.items() if not k.startswith("__")}
        try:
            cmd_str = template.format(**sub)
        except KeyError as e:
            raise ValueError(f"Thiếu tham số {e} trong lệnh '{template}'") from e
        except (ValueError, IndexError):
            # '{' hoặc '}' lẻ (không phải placeholder) → coi là ký tự thật, gửi nguyên văn.
            cmd_str = template
        if is_query:
            result = device._query(cmd_str)
            out: dict[str, Any] = {"text": result, "is_query": True}
            num = _parse_leading_float(result)
            if num is not None:        # đọc được SỐ → vào cột Giá trị + dùng được cho điều kiện If
                out["value"] = num
            return out
        device._write(cmd_str)
        return {"text": cmd_str}
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
        cmd_delay_s: float = 0.1,
    ):
        self._mock = mock
        self._addr = address_map or {}
        self._on_result = on_result or (lambda r: None)
        self._stop_flag = stop_flag or (lambda: False)
        self._settle_wait = settle_wait
        # Nghỉ giữa các lệnh gửi tới thiết bị THẬT (giây). Mock bỏ qua để chạy
        # nhanh. Đặt 0 = tắt. Nhiều máy GPIB đời cũ cần khoảng nghỉ này để ổn định.
        self._cmd_delay_s = cmd_delay_s
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

    def _run_body(self, idx: int, body, iteration: int) -> None:
        """Chạy thân khối — dispatch bước/loop/if (cho phép LỒNG NHAU)."""
        for node in body:
            if self._stop_flag():
                break
            if not getattr(node, "enabled", True):
                continue
            if isinstance(node, ScenarioStep):
                self._run_step(idx, node, iteration=iteration)
            else:
                self._run_node(idx, node)        # loop/if lồng -> đệ quy

    def _run_loop(self, idx: int, loop: LoopBlock) -> None:
        if getattr(loop, "mode", "count") == "until":
            self._run_loop_until(idx, loop)
            return
        self._emit(StepResult(step_index=idx, action="loop", kind="control",
                              node_id=id(loop), text=f"Lặp {loop.count} lần"))
        self._ctx.iter_stack.append(0)
        try:
            for i in range(1, loop.count + 1):
                if self._stop_flag():
                    break
                self._ctx.iter_stack[-1] = i
                self._run_body(idx, loop.body, iteration=i)
        finally:
            self._ctx.iter_stack.pop()

    def _run_loop_until(self, idx: int, loop: LoopBlock) -> None:
        max_iter = max(1, int(getattr(loop, "max_iter", 50)))
        self._emit(StepResult(step_index=idx, action="loop", kind="control",
                              node_id=id(loop),
                              text=f"Lặp đến khi: {loop.condition.describe() if loop.condition else '?'} "
                                   f"(tối đa {max_iter})"))
        self._ctx.iter_stack.append(0)
        reached = False
        i = 0
        try:
            while i < max_iter:
                if self._stop_flag():
                    break
                i += 1
                self._ctx.iter_stack[-1] = i
                self._run_body(idx, loop.body, iteration=i)
                if loop.condition is not None:
                    ok, why = evaluate_condition(loop.condition, self._ctx)
                    if ok:
                        reached = True
                        self._emit(StepResult(step_index=idx, action="loop", kind="control",
                                              node_id=id(loop),
                                              text=f"→ đạt sau {i} vòng ({why})"))
                        break
        finally:
            self._ctx.iter_stack.pop()
        if not reached and not self._stop_flag():
            self._emit(StepResult(step_index=idx, action="loop", kind="control",
                                  node_id=id(loop), ok=False,
                                  error=f"chưa đạt điều kiện sau {i} vòng (max_iter={max_iter})"))

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
        self._run_body(idx, chosen.body, iteration=0)   # nhánh có thể chứa loop/if lồng

    def _resolve_params(self, params: dict) -> dict:
        """Đánh giá tham số dạng '=biểu_thức' theo biến hiện tại; còn lại giữ nguyên."""
        out = {}
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("="):
                out[k] = eval_expr(v[1:], self._ctx.eval_env())
            else:
                out[k] = v
        return out

    def _run_var_action(self, idx: int, step: ScenarioStep, iteration: int) -> None:
        """set_var / compute / collect — thao tác trên biến, không gọi thiết bị."""
        res = StepResult(step_index=idx, action=step.action,
                         node_id=id(step), iteration=iteration)
        try:
            if step.action in ("set_var", "compute"):
                name = step.params.get("name") or step.params.get("target")
                val = eval_expr(step.params.get("expr", ""), self._ctx.eval_env())
                self._ctx.variables[name] = val
                res.text = f"{name} = {val:g}" if isinstance(val, (int, float)) else f"{name} = {val}"
            else:  # collect
                var = step.params.get("var")
                val = eval_expr(step.params.get("source", "$last"), self._ctx.eval_env())
                lst = self._ctx.variables.get(var)
                if not isinstance(lst, list):
                    lst = []
                lst.append(val)
                self._ctx.variables[var] = lst
                res.text = f"{var}[{len(lst)}] ← {val:g}" if isinstance(val, (int, float)) else f"{var} ← {val}"
        except Exception as exc:  # noqa: BLE001
            res.ok = False; res.error = str(exc)
        self._emit(res)

    def _run_step(self, idx: int, step: ScenarioStep, iteration: int) -> None:
        spec = ACTION_SPECS.get(step.action, {})

        if step.action in ("set_var", "compute", "collect"):
            self._run_var_action(idx, step, iteration)
            return

        if not spec.get("needs_device", True):       # wait
            res = StepResult(step_index=idx, action=step.action,
                             node_id=id(step), iteration=iteration)
            try:
                params = dict(step.params)
                if step.action == "wait" and not self._settle_wait:
                    params["seconds"] = 0
                params = self._resolve_params(params)
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
                info = execute_action(step.action, self._devices[dk],
                                      self._resolve_params(step.params))
                res.value = info.get("value"); res.unit = info.get("unit", "")
                res.text = info.get("text", "")
                res.is_query = bool(info.get("is_query", False))
            except Exception as exc:  # noqa: BLE001
                res.ok = False; res.error = str(exc)
            self._emit(res)
            # Nghỉ giữa các lệnh khi chạy máy thật (mock chạy nhanh, không nghỉ).
            if not self._mock and self._cmd_delay_s > 0:
                time.sleep(self._cmd_delay_s)
