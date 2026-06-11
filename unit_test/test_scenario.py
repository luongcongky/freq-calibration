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


# ---------------------------------------------------------------------------
# Delay giữa các lệnh (cmd_delay_s)
# ---------------------------------------------------------------------------

def _open_mock_device(dk):
    """Mở thiết bị giả (mock) để test luồng REAL mà không cần phần cứng."""
    import core.scenario_runner as sr
    return sr.DEVICE_REGISTRY[dk]["cls"](f"MOCK::{dk}", mock=True)


def test_cmd_delay_applied_between_real_commands(monkeypatch):
    import core.scenario_runner as sr
    sleeps: list[float] = []
    monkeypatch.setattr(sr.time, "sleep", lambda s: sleeps.append(s))

    runner = ScenarioRunner(mock=False, address_map={"x": "y"},
                            settle_wait=False, cmd_delay_s=0.1)
    monkeypatch.setattr(runner, "_open_device", _open_mock_device)
    runner.run(_flat_scenario())

    # _flat_scenario có 6 lệnh tới thiết bị (identify×2, set_gate_time,
    # set_frequency, measure_frequency, measure_power) -> 6 lần nghỉ 0.1s.
    assert sleeps.count(0.1) == 6


def test_cmd_delay_skipped_in_mock(monkeypatch):
    import core.scenario_runner as sr
    sleeps: list[float] = []
    monkeypatch.setattr(sr.time, "sleep", lambda s: sleeps.append(s))

    ScenarioRunner(mock=True, cmd_delay_s=0.1).run(_flat_scenario())
    assert 0.1 not in sleeps      # mock không nghỉ giữa lệnh


def test_cmd_delay_zero_disables(monkeypatch):
    import core.scenario_runner as sr
    sleeps: list[float] = []
    monkeypatch.setattr(sr.time, "sleep", lambda s: sleeps.append(s))

    runner = ScenarioRunner(mock=False, address_map={"x": "y"},
                            settle_wait=False, cmd_delay_s=0.0)
    monkeypatch.setattr(runner, "_open_device", _open_mock_device)
    runner.run(_flat_scenario())
    # cmd_delay_s=0 -> không chèn nghỉ nào (sleep(0.0) còn lại chỉ do action wait).
    assert all(s == 0.0 for s in sleeps)


def test_profile_cmd_delay_round_trip(tmp_path):
    from core.profile import ConnectionProfile, ProfileEntry
    prof = ConnectionProfile(name="P", cmd_delay_ms=250)
    prof.set_entry(ProfileEntry(model_key="CNT91", address="GPIB0::7::INSTR"))
    p = tmp_path / "prof.json"
    prof.save_json(p)
    loaded = ConnectionProfile.load_json(p)
    assert loaded.cmd_delay_ms == 250


def test_profile_cmd_delay_default_when_missing():
    # Profile cũ (JSON không có cmd_delay_ms) -> mặc định 100ms.
    from core.profile import ConnectionProfile
    loaded = ConnectionProfile.from_dict({"name": "old", "entries": []})
    assert loaded.cmd_delay_ms == 100


# ---------------------------------------------------------------------------
# raw_scpi: parse value, format an toàn, validate
# ---------------------------------------------------------------------------

class _StubDev:
    """Thiết bị giả tối giản cho test execute_action(raw_scpi)."""
    def __init__(self, resp: str = ""):
        self._resp = resp
        self.written: list[str] = []

    def _query(self, cmd: str, **_kw) -> str:
        return self._resp

    def _write(self, cmd: str) -> None:
        self.written.append(cmd)


def test_raw_scpi_query_sets_numeric_value():
    from core.scenario_runner import execute_action
    info = execute_action("raw_scpi", _StubDev("1.2345E9"),
                          {"__template__": "MEAS:FREQ?", "__is_query__": True})
    assert info["value"] == pytest.approx(1.2345e9)
    assert info["text"] == "1.2345E9"


def test_raw_scpi_query_value_with_unit_suffix():
    from core.scenario_runner import execute_action
    info = execute_action("raw_scpi", _StubDev("1.0E9 HZ"),
                          {"__template__": "FREQ?", "__is_query__": True})
    assert info["value"] == pytest.approx(1.0e9)


def test_raw_scpi_query_nonnumeric_keeps_text_only():
    from core.scenario_runner import execute_action
    info = execute_action("raw_scpi", _StubDev("ON"),
                          {"__template__": "OUTP?", "__is_query__": True})
    assert "value" not in info
    assert info["text"] == "ON"


def test_raw_scpi_query_value_feeds_if_condition():
    # Giá trị đọc bằng raw_scpi phải dùng được cho điều kiện If/measure.
    from core.scenario_runner import ScenarioRunner

    def open_stub(dk):
        from unittest.mock import MagicMock
        m = MagicMock()
        m._query.return_value = "5.0"
        return m

    scn = Scenario(nodes=[
        ScenarioStep(action="raw_scpi", devices=["CNT91"],
                     params={"__template__": "MEAS:FREQ?", "__is_query__": True}),
        IfBlock(branches=[
            Branch(condition=Condition(kind="measure", op=">", value=1.0),
                   body=[ScenarioStep(action="raw_scpi", devices=["CNT91"],
                                      params={"__template__": "*CLS", "__is_query__": False})]),
        ]),
    ])
    runner = ScenarioRunner(mock=False, address_map={"CNT91": "x"}, cmd_delay_s=0.0)
    runner._open_device = open_stub
    results = runner.run(scn)
    # node If phải chọn được nhánh (5.0 > 1.0) → có dòng control "→ nhánh 1".
    assert any(r.kind == "control" and "nhánh 1" in r.text for r in results)


def test_raw_scpi_lone_brace_sent_literally():
    from core.scenario_runner import execute_action
    dev = _StubDev("")
    info = execute_action("raw_scpi", dev,
                          {"__template__": "CONF:LIST #{", "__is_query__": False})
    assert info["text"] == "CONF:LIST #{"
    assert dev.written == ["CONF:LIST #{"]


def test_raw_scpi_missing_param_raises():
    from core.scenario_runner import execute_action
    with pytest.raises(ValueError, match="Thiếu tham số"):
        execute_action("raw_scpi", _StubDev(""),
                       {"__template__": "FREQ {Hz}", "__is_query__": False})


def test_validate_raw_scpi_missing_param_value():
    scn = Scenario(nodes=[ScenarioStep(action="raw_scpi", devices=["CNT91"],
        params={"__template__": "SENS:GATE:TIME {s}", "__is_query__": False})])
    problems = validate_scenario(scn)
    assert any("thiếu giá trị tham số" in p for p in problems)


def test_validate_raw_scpi_query_not_marked():
    scn = Scenario(nodes=[ScenarioStep(action="raw_scpi", devices=["CNT91"],
        params={"__template__": "MEAS:FREQ?", "__is_query__": False})])
    problems = validate_scenario(scn)
    assert any("truy vấn" in p for p in problems)


def test_validate_raw_scpi_clean():
    scn = Scenario(nodes=[ScenarioStep(action="raw_scpi", devices=["CNT91"],
        params={"__template__": "MEAS:FREQ?", "__is_query__": True})])
    assert validate_scenario(scn) == []


# ---------------------------------------------------------------------------
# Định dạng số kiểu VN (chấm nghìn, phẩy thập phân, không khoa học)
# ---------------------------------------------------------------------------

# Lưu ý: float chỉ biểu diễn CHÍNH XÁC số nguyên tới ~2^53 (~9e15). Tần số thật
# (≤ vài chục GHz = ~5e10) nằm thừa trong vùng này nên hiển thị luôn chính xác.
@pytest.mark.parametrize("value,expected", [
    (1e11,            "100.000.000.000"),
    (1_000_000,       "1.000.000"),
    (1234567.89,      "1.234.567,89"),
    (-10.5,           "-10,5"),
    (0.1,             "0,1"),
    (0.0,             "0"),
    (50e9,            "50.000.000.000"),
    (1.2345e9,        "1.234.500.000"),
    (1_000_000_000_000_000, "1.000.000.000.000.000"),   # 1e15, vẫn chính xác
])
def test_format_number_vi(value, expected):
    from core.scenario_runner import format_number_vi
    assert format_number_vi(value) == expected


def test_summary_uses_vi_format():
    r = StepResult(action="raw_scpi", value=1e11, unit="Hz")
    assert "100.000.000.000" in r.summary()
    assert "e+" not in r.summary().lower()
