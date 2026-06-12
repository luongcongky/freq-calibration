"""
unit_test/test_phase3_loop.py
=============================
Phase 3: Loop-until + $iter + lồng khối (nesting). Có test end-to-end đo độ nhạy
vòng kín: until(error<=thr) bao Loop count=3, ramp công suất theo $iter.
"""

import pytest

from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition, validate_scenario,
)
from core.scenario_runner import ScenarioRunner


def _run(scn, **kw):
    r = ScenarioRunner(mock=True, settle_wait=False, **kw)
    return r, r.run(scn)


def sv(name, expr):
    return ScenarioStep(action="set_var", params={"name": name, "expr": expr})


# ---------------------------------------------------------------------------
# Loop-until
# ---------------------------------------------------------------------------

def test_loop_until_stops_on_condition():
    scn = Scenario(nodes=[
        sv("n", "0"),
        LoopBlock(mode="until", max_iter=10,
                  condition=Condition(kind="expr", expr="n", op=">=", value=3),
                  body=[sv("n", "n + 1")]),
    ])
    r, results = _run(scn)
    assert r._ctx.variables["n"] == 3
    assert any("đạt sau 3 vòng" in x.text for x in results if x.kind == "control")


def test_loop_until_max_iter_cap():
    scn = Scenario(nodes=[
        sv("n", "0"),
        LoopBlock(mode="until", max_iter=5,
                  condition=Condition(kind="expr", expr="n", op=">", value=100),
                  body=[sv("n", "n + 1")]),
    ])
    r, results = _run(scn)
    assert r._ctx.variables["n"] == 5
    assert any(not x.ok and "chưa đạt" in x.error for x in results)


# ---------------------------------------------------------------------------
# $iter trong loop count + lồng khối
# ---------------------------------------------------------------------------

def test_iter_in_count_loop():
    scn = Scenario(nodes=[
        sv("acc", "0"),
        LoopBlock(count=3, body=[sv("acc", "acc + $iter")]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["acc"] == 6        # 1+2+3


def test_nested_loops():
    scn = Scenario(nodes=[
        sv("total", "0"),
        LoopBlock(count=2, body=[
            LoopBlock(count=3, body=[sv("total", "total + 1")]),
        ]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["total"] == 6      # 2*3


def test_if_inside_loop():
    scn = Scenario(nodes=[
        sv("hits", "0"),
        LoopBlock(count=4, body=[
            IfBlock(branches=[
                Branch(condition=Condition(kind="expr", expr="$iter", op=">=", value=3),
                       body=[sv("hits", "hits + 1")]),
                Branch(condition=None, body=[sv("hits", "hits + 0")]),
            ]),
        ]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["hits"] == 2       # $iter = 3,4


# ---------------------------------------------------------------------------
# JSON round-trip (until + lồng)
# ---------------------------------------------------------------------------

def test_until_loop_json_round_trip(tmp_path):
    scn = Scenario(nodes=[
        sv("n", "0"),
        LoopBlock(mode="until", max_iter=7,
                  condition=Condition(kind="expr", expr="n", op=">=", value=2),
                  body=[
                      LoopBlock(count=2, body=[sv("n", "n + 1")]),   # lồng
                  ]),
    ])
    p = tmp_path / "u.json"
    scn.save_json(p)
    scn2 = Scenario.load_json(p)
    lb = scn2.nodes[1]
    assert lb.mode == "until" and lb.max_iter == 7
    assert lb.condition.kind == "expr" and lb.condition.expr == "n"
    assert isinstance(lb.body[0], LoopBlock) and lb.body[0].count == 2    # giữ lồng


def test_validate_until_needs_condition():
    scn = Scenario(nodes=[LoopBlock(mode="until", body=[sv("n", "1")])])
    problems = validate_scenario(scn)
    assert any("cần điều kiện dừng" in p for p in problems)


# ---------------------------------------------------------------------------
# END-TO-END: đo độ nhạy vòng kín (until bao count=3 + ramp công suất $iter)
# ---------------------------------------------------------------------------

class _StubGen:
    """Máy phát giả: ghi nhận công suất đã đặt."""
    def __init__(self):
        self.power = 0.0
    def _write(self, cmd):
        if "POW:POW" in cmd:
            self.power = float(cmd.split()[-2])
    def _query(self, cmd, **kw):
        return "0"
    def disconnect(self):
        pass


class _StubCnt:
    """Máy đếm giả: tần số đo lệch giảm dần khi công suất tăng."""
    def __init__(self, gen, f_set):
        self.gen = gen
        self.f_set = f_set
    def _write(self, cmd):
        pass
    def _query(self, cmd, **kw):
        offset = max(0.0, 30.0 - 50.0 * (self.gen.power + 5.0))   # -5dBm:+30Hz, -4.5:+5Hz
        return str(self.f_set + offset)
    def disconnect(self):
        pass


def _raw(tmpl, orig, devs, query=False, **params):
    p = {"__template__": tmpl, "__is_query__": query, "__cmd_original__": orig}
    p.update(params)
    return ScenarioStep(action="raw_scpi", devices=devs, params=p)


def test_sensitivity_closed_loop():
    F_SET = 100_000_000.0
    scn = Scenario(nodes=[
        sv("f_set", "100000000"),
        sv("p_base", "-5"),
        _raw("SOUR1:FREQ:CW {Hz} HZ", "SOUR1:FREQ:CW <Hz> HZ", ["SMW200A"], Hz="=f_set"),
        LoopBlock(
            mode="until", max_iter=10,
            condition=Condition(kind="expr", expr="error", op="<=", value=1e-7),
            body=[
                _raw("SOUR1:POW:POW {pw} dBm", "SOUR1:POW:POW <pw> dBm", ["SMW200A"],
                     pw="=p_base + 0.5*($iter-1)"),
                sv("samples", "[]"),
                LoopBlock(count=3, body=[
                    _raw("MEAS:FREQ?", "MEAS:FREQ?", ["CNT91"], query=True),
                    ScenarioStep(action="collect", params={"var": "samples", "source": "$last"}),
                ]),
                ScenarioStep(action="compute", params={"name": "f_avg", "expr": "avg(samples)"}),
                ScenarioStep(action="compute", params={"name": "error",
                                                        "expr": "abs(f_avg - f_set)/f_set"}),
            ],
        ),
    ])
    assert validate_scenario(scn) == []

    gen = _StubGen()
    cnt = _StubCnt(gen, F_SET)
    r = ScenarioRunner(mock=False, address_map={"SMW200A": "x", "CNT91": "y"},
                       settle_wait=False, cmd_delay_s=0.0)
    r._open_device = lambda dk: gen if dk == "SMW200A" else cnt
    results = r.run(scn)

    assert r._ctx.variables["error"] <= 1e-7          # hội tụ
    assert gen.power == pytest.approx(-4.5)           # ramp 1 bậc (iter 2)
    assert len(r._ctx.variables["samples"]) == 3      # trung bình 3 lần đo
    assert any("đạt sau 2 vòng" in x.text for x in results if x.kind == "control")
