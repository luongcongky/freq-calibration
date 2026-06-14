"""
unit_test/test_goto.py
======================
GOTO + nhãn (label): nhảy tới điểm thao tác cấp ngoài cùng, goto đặt bất kỳ
(kể cả trong If/Loop), kèm cap chống vòng lặp vô hạn.
"""

import pytest

from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition, validate_scenario,
)
from core.scenario_runner import ScenarioRunner
import core.scenario_runner as sr


def _run(scn):
    r = ScenarioRunner(mock=True, settle_wait=False)
    return r, r.run(scn)


def sv(name, expr):
    return ScenarioStep(action="set_var", params={"name": name, "expr": expr})

def label(name):
    return ScenarioStep(action="label", params={"name": name})

def goto(target):
    return ScenarioStep(action="goto", params={"target": target})


# ---------------------------------------------------------------------------
# Vòng lặp bằng goto (trong nhánh If) — có biến đếm để dừng
# ---------------------------------------------------------------------------

def test_goto_loop_with_counter():
    scn = Scenario(nodes=[
        sv("n", "0"),
        label("start"),
        sv("n", "n + 1"),
        IfBlock(branches=[
            Branch(condition=Condition(kind="expr", expr="n", op="<", value=3),
                   body=[goto("start")]),
        ]),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["n"] == 3        # chạy thân 3 lần rồi dừng


# ---------------------------------------------------------------------------
# Goto từ trong Loop -> nhảy ra nhãn cấp ngoài (unwind + bỏ qua node ở giữa)
# ---------------------------------------------------------------------------

def test_goto_unwinds_loop_and_skips():
    scn = Scenario(nodes=[
        sv("x", "0"),
        LoopBlock(count=5, body=[
            sv("x", "x + 1"),
            IfBlock(branches=[
                Branch(condition=Condition(kind="expr", expr="x", op=">=", value=2),
                       body=[goto("after")]),
            ]),
        ]),
        sv("skipped", "1"),     # bị nhảy QUA -> không chạy
        label("after"),
        sv("done", "1"),
    ])
    r, _ = _run(scn)
    assert r._ctx.variables["x"] == 2            # thoát loop sớm (chưa tới 5)
    assert "skipped" not in r._ctx.variables     # bị bỏ qua
    assert r._ctx.variables["done"] == 1         # tới được sau nhãn


# ---------------------------------------------------------------------------
# Goto tiến (nhảy về phía trước, bỏ qua đoạn giữa)
# ---------------------------------------------------------------------------

def test_goto_forward_skips():
    scn = Scenario(nodes=[
        goto("end"),
        sv("middle", "1"),
        label("end"),
        sv("done", "1"),
    ])
    r, _ = _run(scn)
    assert "middle" not in r._ctx.variables
    assert r._ctx.variables["done"] == 1


# ---------------------------------------------------------------------------
# Cap chống vòng lặp vô hạn
# ---------------------------------------------------------------------------

def test_goto_infinite_loop_capped(monkeypatch):
    monkeypatch.setattr(sr, "MAX_GOTO", 5)
    scn = Scenario(nodes=[label("L"), goto("L")])     # goto vô điều kiện
    _, results = _run(scn)
    assert any(not x.ok and "vô hạn" in x.error for x in results)


def test_goto_missing_label_at_runtime(monkeypatch):
    monkeypatch.setattr(sr, "MAX_GOTO", 5)
    # validate sẽ chặn, nhưng kiểm tra runtime cũng báo lỗi an toàn
    scn = Scenario(nodes=[goto("khong_co")])
    _, results = _run(scn)
    assert any(not x.ok and "không thấy nhãn" in x.error for x in results)


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def test_validate_goto_unknown_target():
    scn = Scenario(nodes=[label("A"), goto("B")])
    assert any("không tồn tại" in p for p in validate_scenario(scn))


def test_validate_label_no_name():
    scn = Scenario(nodes=[ScenarioStep(action="label", params={})])
    assert any("thiếu tên" in p for p in validate_scenario(scn))


def test_validate_duplicate_label():
    scn = Scenario(nodes=[label("A"), label("A"), goto("A")])
    assert any("trùng" in p for p in validate_scenario(scn))


def test_validate_goto_ok():
    scn = Scenario(nodes=[label("A"), sv("x", "1"), goto("A")])
    assert validate_scenario(scn) == []
