"""
unit_test/test_scenario.py
==========================
Test mô hình kịch bản DẠNG CÂY (Step/Loop/If) và bộ thực thi ở chế độ MOCK.
"""

import pytest

from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    actions_for_devices, validate_scenario, node_kind,
)
from core.scenario_runner import ScenarioRunner, StepResult, evaluate_condition, _Ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_scenario() -> Scenario:
    return Scenario(name="Phẳng", nodes=[
        ScenarioStep(action="identify", devices=["CNT91", "N1913A"]),
        ScenarioStep(action="set_gate_time", devices=["CNT91"], params={"gate_time": 0.1}),
        ScenarioStep(action="set_frequency", devices=["N1913A"], params={"freq_hz": 1e9}),
        ScenarioStep(action="wait", devices=[], params={"seconds": 0.0}),
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        ScenarioStep(action="measure_power", devices=["N1913A"]),
    ])


# ---------------------------------------------------------------------------
# Model phẳng (giữ tương thích)
# ---------------------------------------------------------------------------

def test_actions_for_devices_intersection():
    common = actions_for_devices(["CNT91", "N1913A"])
    assert "identify" in common and "status" in common
    assert "set_gate_time" not in common
    assert "measure_power" not in common
    assert "wait" in common


def test_json_round_trip_flat(tmp_path):
    scn = _flat_scenario()
    p = tmp_path / "s.json"
    scn.save_json(p)
    loaded = Scenario.load_json(p)
    assert len(loaded.nodes) == 6
    assert loaded.nodes[0].devices == ["CNT91", "N1913A"]


def test_backward_compat_old_steps_format():
    # Kịch bản cũ dạng {"steps": [...]} vẫn nạp được thành nodes.
    scn = Scenario.from_dict({"name": "cũ", "steps": [
        {"action": "identify", "devices": ["CNT91"]},
    ]})
    assert len(scn.nodes) == 1 and node_kind(scn.nodes[0]) == "step"


def test_move_node():
    scn = _flat_scenario()
    first = scn.nodes[0]
    assert scn.move(0, +1) == 1
    assert scn.nodes[1] is first


def test_validate_clean_flat():
    assert validate_scenario(_flat_scenario()) == []


def test_validate_wrong_category():
    scn = Scenario(nodes=[ScenarioStep(action="set_gate_time", devices=["N1913A"],
                                       params={"gate_time": 0.1})])
    assert any("không áp dụng" in p for p in validate_scenario(scn))


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

def test_loop_repeats_body():
    scn = Scenario(nodes=[LoopBlock(count=3, body=[
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
    ])])
    results = ScenarioRunner(mock=True, settle_wait=False).run(scn)
    measures = [r for r in results if r.action == "measure_frequency"]
    assert len(measures) == 3
    assert {r.iteration for r in measures} == {1, 2, 3}


def test_loop_json_round_trip(tmp_path):
    scn = Scenario(nodes=[LoopBlock(count=5, body=[
        ScenarioStep(action="identify", devices=["CNT91"]),
    ])])
    p = tmp_path / "loop.json"
    scn.save_json(p)
    loaded = Scenario.load_json(p)
    assert node_kind(loaded.nodes[0]) == "loop"
    assert loaded.nodes[0].count == 5
    assert len(loaded.nodes[0].body) == 1


def test_loop_validate_errors():
    scn = Scenario(nodes=[LoopBlock(count=0, body=[])])
    probs = validate_scenario(scn)
    assert any("≥ 1" in p for p in probs)
    assert any("chưa có bước con" in p for p in probs)


# ---------------------------------------------------------------------------
# If / điều kiện
# ---------------------------------------------------------------------------

def test_if_measure_branch_taken():
    # Đo tần số (mock CNT91 ~10 MHz) rồi rẽ nhánh theo ngưỡng.
    scn = Scenario(nodes=[
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        IfBlock(branches=[
            Branch(condition=Condition(kind="measure", device="CNT91", op=">", value=1e6),
                   body=[ScenarioStep(action="identify", devices=["CNT91"])]),
            Branch(condition=None,   # ELSE
                   body=[ScenarioStep(action="identify", devices=["N1913A"])]),
        ]),
    ])
    results = ScenarioRunner(mock=True).run(scn)
    idents = [r for r in results if r.action == "identify"]
    # CNT91 ~10 MHz > 1 MHz -> nhánh IF (identify CNT91), KHÔNG chạy ELSE.
    assert len(idents) == 1 and idents[0].device_key == "CNT91"


def test_if_else_branch_taken():
    scn = Scenario(nodes=[
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        IfBlock(branches=[
            Branch(condition=Condition(kind="measure", device="CNT91", op=">", value=1e12),
                   body=[ScenarioStep(action="identify", devices=["CNT91"])]),
            Branch(condition=None,
                   body=[ScenarioStep(action="identify", devices=["N1913A"])]),
        ]),
    ])
    results = ScenarioRunner(mock=True).run(scn)
    idents = [r for r in results if r.action == "identify"]
    assert len(idents) == 1 and idents[0].device_key == "N1913A"


def test_condition_status():
    ctx = _Ctx(last_ok=True)
    ok, _ = evaluate_condition(Condition(kind="status", status="ok"), ctx)
    assert ok
    ok2, _ = evaluate_condition(Condition(kind="status", status="error"), ctx)
    assert not ok2


def test_condition_between():
    ctx = _Ctx(last_value=5.0)
    assert evaluate_condition(Condition(op="between", value=1, value2=10), ctx)[0]
    assert not evaluate_condition(Condition(op="between", value=6, value2=10), ctx)[0]


def test_if_validate_too_many_else():
    scn = Scenario(nodes=[IfBlock(branches=[
        Branch(condition=None, body=[ScenarioStep(action="identify", devices=["CNT91"])]),
        Branch(condition=None, body=[ScenarioStep(action="identify", devices=["CNT91"])]),
    ])])
    assert any("ELSE" in p for p in validate_scenario(scn))


# ---------------------------------------------------------------------------
# Runner cơ bản
# ---------------------------------------------------------------------------

def test_runner_executes_flat():
    results = ScenarioRunner(mock=True, settle_wait=False).run(_flat_scenario())
    # identify(2) + gate(1) + setfreq(1) + wait(1) + measfreq(1) + measpow(1) = 7
    assert len([r for r in results if r.kind == "step"]) == 7
    assert all(r.ok for r in results)


def test_runner_disabled_node_skipped():
    scn = Scenario(nodes=[
        ScenarioStep(action="identify", devices=["CNT91"], enabled=False),
        ScenarioStep(action="identify", devices=["CNT91"], enabled=True),
    ])
    results = ScenarioRunner(mock=True).run(scn)
    assert len([r for r in results if r.action == "identify"]) == 1


def test_runner_stop_flag():
    results = ScenarioRunner(mock=True, stop_flag=lambda: True).run(_flat_scenario())
    assert results == []


def test_runner_real_without_address_raises():
    scn = Scenario(nodes=[ScenarioStep(action="identify", devices=["CNT91"])])
    with pytest.raises(ValueError, match="thiếu địa chỉ VISA"):
        ScenarioRunner(mock=False, address_map={}).run(scn)
