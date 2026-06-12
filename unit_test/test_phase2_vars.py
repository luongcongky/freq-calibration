"""
unit_test/test_phase2_vars.py
=============================
Phase 2: biến + set_var/compute/collect + tham số '=expr' + điều kiện kind="expr".
"""

import pytest

from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    validate_scenario,
)
from core.scenario_runner import ScenarioRunner


def _run(scn):
    r = ScenarioRunner(mock=True, settle_wait=False)
    results = r.run(scn)
    return r, results


def sv(name, expr):
    return ScenarioStep(action="set_var", params={"name": name, "expr": expr})

def comp(name, expr):
    return ScenarioStep(action="compute", params={"name": name, "expr": expr})

def coll(var, source="$last"):
    return ScenarioStep(action="collect", params={"var": var, "source": source})


# ---------------------------------------------------------------------------
# set_var / compute / list + avg
# ---------------------------------------------------------------------------

def test_set_var_and_compute():
    scn = Scenario(nodes=[
        sv("samples", "[10.0, 20.0, 30.0]"),
        comp("avg_v", "avg(samples)"),
        comp("err", "abs(avg_v - 25)/25"),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["avg_v"] == pytest.approx(20.0)
    assert r._ctx.variables["err"] == pytest.approx(0.2)


def test_collect_appends_last():
    # collect nối $last vào list; ở đây set $last gián tiếp qua biến giả lập.
    scn = Scenario(nodes=[
        sv("xs", "[]"),
        coll("xs", "5"),
        coll("xs", "7"),
        comp("s", "avg(xs)"),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["xs"] == [5, 7]
    assert r._ctx.variables["s"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Điều kiện kind="expr"
# ---------------------------------------------------------------------------

def test_expr_condition_branch():
    scn = Scenario(nodes=[
        comp("err", "0.2"),
        IfBlock(branches=[
            Branch(condition=Condition(kind="expr", expr="err", op=">", value=0.1),
                   body=[sv("flag", "1")]),
            Branch(condition=None, body=[sv("flag", "0")]),
        ]),
    ])
    r, results = _run(scn)
    assert r._ctx.variables["flag"] == 1
    assert any(x.kind == "control" and "nhánh 1" in x.text for x in results)


def test_expr_condition_else():
    scn = Scenario(nodes=[
        comp("err", "0.05"),
        IfBlock(branches=[
            Branch(condition=Condition(kind="expr", expr="err", op=">", value=0.1),
                   body=[sv("flag", "1")]),
            Branch(condition=None, body=[sv("flag", "0")]),
        ]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["flag"] == 0


# ---------------------------------------------------------------------------
# Tham số '=expr' cho raw_scpi
# ---------------------------------------------------------------------------

def test_param_expression_resolved():
    scn = Scenario(nodes=[
        sv("p", "-5"),
        ScenarioStep(action="raw_scpi", devices=["SMW200A"], params={
            "__template__": "SOUR{ch}:POW:POW {dBm} dBm",
            "__is_query__": False,
            "__cmd_original__": "SOUR<ch>:POW:POW <dBm> dBm",
            "ch": 1, "dBm": "=p + 0.5",
        }),
    ])
    _, results = _run(scn)
    pw = [x for x in results if x.action == "raw_scpi"][-1]
    assert "-4.5" in pw.text       # =p+0.5 = -4.5 đã thay vào lệnh


# ---------------------------------------------------------------------------
# End-to-end kiểu đo độ nhạy (trung bình -> sai số -> rẽ nhánh theo sai số)
# ---------------------------------------------------------------------------

def test_sensitivity_like_flow():
    scn = Scenario(nodes=[
        sv("f_set", "100000000"),
        sv("samples", "[100000001.0, 100000000.0, 99999999.0]"),
        comp("f_avg", "avg(samples)"),
        comp("error", "abs(f_avg - f_set)/f_set"),
        IfBlock(branches=[
            Branch(condition=Condition(kind="expr", expr="error", op=">", value=1e-7),
                   body=[sv("verdict", "1")]),     # lệch -> cần tăng công suất
            Branch(condition=None, body=[sv("verdict", "0")]),  # đạt
        ]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["f_avg"] == pytest.approx(100000000.0)
    assert r._ctx.variables["error"] == pytest.approx(0.0, abs=1e-9)
    assert r._ctx.variables["verdict"] == 0      # error ~0 <= 1e-7 -> đạt


# ---------------------------------------------------------------------------
# Validate bắt lỗi biểu thức
# ---------------------------------------------------------------------------

def test_validate_bad_expr():
    scn = Scenario(nodes=[comp("x", "1 + * 2")])
    problems = validate_scenario(scn)
    assert any("biểu thức lỗi" in p for p in problems)


def test_validate_missing_var_name():
    scn = Scenario(nodes=[ScenarioStep(action="set_var", params={"expr": "1"})])
    problems = validate_scenario(scn)
    assert any("thiếu tên biến" in p for p in problems)


def test_validate_expr_condition_ok():
    scn = Scenario(nodes=[
        comp("err", "0.2"),
        IfBlock(branches=[
            Branch(condition=Condition(kind="expr", expr="err", op="<", value=0.1),
                   body=[sv("f", "1")]),
            Branch(condition=None, body=[sv("f", "0")]),
        ]),
    ])
    assert validate_scenario(scn) == []
