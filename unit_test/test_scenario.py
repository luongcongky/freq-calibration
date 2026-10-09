"""
unit_test/test_scenario.py
==========================
Test mô hình kịch bản DẠNG CÂY (Step/Loop/If) và bộ thực thi ở chế độ MOCK.
"""

import logging

import pytest

from core.scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    actions_for_devices, validate_scenario, node_kind, enumerate_nodes,
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


def test_from_dict_rejects_file_without_nodes_or_steps_key():
    """BUG-19: mở nhầm file khác (vd phiên kiểm định .json, top-level
    {"template_id", "meta", "tests"}) trong 'Mở kịch bản' trước đây âm
    thầm thành kịch bản RỖNG hợp lệ (0 node), báo "Đã mở" như bình thường —
    phải raise để GUI báo lỗi rõ ràng (gui/scenario_grid.py::load_scenario_file,
    gui/flow_editor.py::_do_pick_scenario đều đã bọc try/except sẵn)."""
    with pytest.raises(ValueError, match="không phải file kịch bản"):
        Scenario.from_dict({"template_id": "X", "meta": {}, "tests": []})


def test_from_dict_accepts_explicitly_empty_nodes():
    """Kịch bản THẬT nhưng rỗng ({"nodes": []}) vẫn phải nạp được, không bị
    chặn nhầm như file sai định dạng ở test trên."""
    scn = Scenario.from_dict({"name": "rỗng", "nodes": []})
    assert scn.nodes == []


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
# report_val — đẩy giá trị vào mảng kết quả tuần tự (thay report_tag cũ).
# Không cần khai tên bảng đích: 1 lần chạy kịch bản luôn ứng đúng 1 bài
# test/1 bảng, nên bảng đích do bên gọi map_results() biết trước, không
# phải do kịch bản tự khai (tránh lỗi khai sai/quên đổi khi tái dùng file
# kịch bản cho bài test khác).
# ---------------------------------------------------------------------------

def test_report_val_validate_clean():
    scn = Scenario(nodes=[
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        ScenarioStep(action="report_val", params={"value": "$last"}),
    ])
    assert validate_scenario(scn) == []


def test_report_val_validate_bad_expr():
    scn = Scenario(nodes=[
        ScenarioStep(action="report_val", params={"value": "1 +"}),
    ])
    probs = validate_scenario(scn)
    assert probs   # biểu thức hỏng vẫn phải bị báo lỗi


def test_report_val_emits_value():
    scn = Scenario(nodes=[
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        ScenarioStep(action="report_val", params={"value": "$last"}),
    ])
    results = ScenarioRunner(mock=True, settle_wait=False).run(scn)
    pushes = [r for r in results if r.action == "report_val"]
    assert len(pushes) == 1
    assert pushes[0].value is not None


def test_report_val_inside_loop_pushes_one_value_per_iteration():
    """Trước đây report_tag tĩnh trên step khiến mọi vòng lặp ghi đè cùng 1
    row_key (chỉ giữ được giá trị của lần lặp cuối). report_val giải quyết
    bằng cách đẩy TUẦN TỰ — mỗi vòng lặp tạo 1 StepResult report_val riêng,
    result_mapper tự tách theo thứ tự (xem test_result_mapper.py)."""
    scn = Scenario(nodes=[LoopBlock(count=3, body=[
        ScenarioStep(action="set_var", params={"name": "x", "expr": "$iter * 100"}),
        ScenarioStep(action="report_val", params={"value": "x"}),
    ])])
    results = ScenarioRunner(mock=True, settle_wait=False).run(scn)
    pushes = [r for r in results if r.action == "report_val"]
    assert len(pushes) == 3
    assert [r.value for r in pushes] == [100.0, 200.0, 300.0]


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


def test_runner_stopped_early_false_when_scenario_runs_to_completion():
    runner = ScenarioRunner(mock=True)
    runner.run(_flat_scenario())
    assert runner.stopped_early is False, (
        "stopped_early=True dù chạy hết kịch bản -> sẽ hiện cảnh báo sai (R5-01)")


def test_wait_step_interrupted_by_stop_flag_quickly(monkeypatch):
    """R4-05 (test_reports/2026-10-08_round5): bấm Dừng lúc kịch bản đang ở
    bước WAIT (vd 35s chờ zero) trước đây phải chờ gần hết 35s mới dừng, vì
    time.sleep(35) gọi 1 lần không có cách nào ngắt giữa chừng. Giờ WAIT
    phải chia nhỏ sleep & dừng NGAY khi stop_flag lên True."""
    import core.scenario_runner as sr
    sleeps: list[float] = []
    monkeypatch.setattr(sr.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def stop_flag():
        calls["n"] += 1
        return calls["n"] > 3   # dừng sau vài lần poll, còn lâu mới hết 35s

    scn = Scenario(nodes=[
        ScenarioStep(action="wait", devices=[], params={"seconds": 35.0}),
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
    ])
    runner = ScenarioRunner(mock=True, stop_flag=stop_flag)
    runner.run(scn)

    assert sleeps, "WAIT không gọi sleep() nào — không mô phỏng đúng hành vi chờ"
    assert all(s <= ScenarioRunner._WAIT_POLL_S + 1e-9 for s in sleeps), (
        f"WAIT vẫn sleep() nguyên 1 cục lớn, không chia nhỏ để ngắt được: {sleeps}")
    assert sum(sleeps) < 35.0, (
        f"Tổng thời gian sleep ({sum(sleeps)}s) gần bằng nguyên 35s — "
        f"không dừng sớm được (R4-05)")
    assert runner.stopped_early is True   # node 2 (measure_frequency) chưa kịp chạy


def test_runner_stop_mid_run_auto_turns_off_rf(caplog):
    """R4-01 (test_reports/2026-10-08_round4): khách bấm Dừng giữa lúc đo
    thật -> SMW200A vẫn bật RF vì bước dọn dẹp ở cuối kịch bản không chạy.
    Cho phép node "rf_on" chạy xong (RF đã BẬT), rồi dừng TRƯỚC node kế
    tiếp -> finally phải tự rf_off() + log cảnh báo dừng sớm."""
    calls = {"n": 0}

    def stop_flag():
        calls["n"] += 1
        return calls["n"] > 1  # cho qua node đầu (rf_on), dừng trước node 2

    scn = Scenario(nodes=[
        ScenarioStep(action="rf_on", devices=["SMW200A"]),
        ScenarioStep(action="measure_frequency", devices=["CNT91"]),
    ])
    runner = ScenarioRunner(mock=True, stop_flag=stop_flag)
    with caplog.at_level(logging.WARNING):
        results = runner.run(scn)

    assert len(results) == 1  # chỉ node rf_on kịp chạy
    smw = runner._devices["SMW200A"]
    assert smw._mock_rf == "0", "RF chưa tự tắt khi dừng giữa đường (R4-01)"
    assert runner.stopped_early is True, (
        "stopped_early phải True để giao diện tự cảnh báo (R5-01)")
    assert any("dừng SỚM" in r.message for r in caplog.records), (
        "Không cảnh báo dừng sớm (R4-01) — người dùng có thể lầm máy đã an toàn")


def test_runner_no_cleanup_warning_logged_when_no_device_ever_opened(caplog):
    """Ghi chú trong test_reports/2026-10-09_khong_thiet_bi: cảnh báo 'dừng
    SỚM ... CHƯA chạy' vẫn log ngay cả khi KHÔNG mở được thiết bị nào (vd
    toàn bộ máy đang tắt) — không có gì để dọn dẹp cả, chỉ gây nhiễu log."""
    scn = Scenario(nodes=[ScenarioStep(action="identify", devices=["CNT91"])])
    runner = ScenarioRunner(mock=False, address_map={})  # thiếu địa chỉ -> lỗi ngay thiết bị đầu
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            runner.run(scn)
    assert not any("dừng SỚM" in r.message for r in caplog.records), (
        f"Vẫn log cảnh báo dọn dẹp dù chưa mở được thiết bị nào: {caplog.records}")


def test_runner_real_without_address_raises():
    scn = Scenario(nodes=[ScenarioStep(action="identify", devices=["CNT91"])])
    with pytest.raises(ValueError, match="thiếu địa chỉ VISA"):
        ScenarioRunner(mock=False, address_map={}).run(scn)


# ---------------------------------------------------------------------------
# Delay giữa các lệnh (cmd_delay_s)
# ---------------------------------------------------------------------------

def _open_mock_device(dk):
    """Mở thiết bị giả (mock) để test luồng REAL mà không cần phần cứng."""
    from core.custom_devices import get_device_registry
    return get_device_registry()[dk]["cls"](f"MOCK::{dk}", mock=True)


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


# ---------------------------------------------------------------------------
# Tự dừng khi thiết bị THẬT gặp sự cố (không hầm hố tiếp lệnh vào máy hỏng)
# ---------------------------------------------------------------------------

def _loop_scenario(count: int) -> Scenario:
    return Scenario(name="Loop", nodes=[
        LoopBlock(count=count, body=[
            ScenarioStep(action="measure_frequency", devices=["CNT91"]),
        ]),
    ])


def test_real_run_auto_stops_when_device_fails_mid_loop(monkeypatch):
    import core.scenario_runner as sr
    monkeypatch.setattr(sr, "execute_action",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mất kết nối")))

    runner = ScenarioRunner(mock=False, address_map={"x": "y"}, settle_wait=False, cmd_delay_s=0.0)
    monkeypatch.setattr(runner, "_open_device", _open_mock_device)
    results = runner.run(_loop_scenario(100))

    # Phải dừng NGAY sau lần lỗi đầu tiên — không chạy hết 100 vòng.
    device_results = [r for r in results if r.action == "measure_frequency"]
    assert len(device_results) == 1
    assert device_results[0].ok is False
    assert runner.stop_reason and "CNT91" in runner.stop_reason


def test_mock_run_does_not_auto_stop_on_error(monkeypatch):
    import core.scenario_runner as sr
    monkeypatch.setattr(sr, "execute_action",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mất kết nối")))

    runner = ScenarioRunner(mock=True)
    results = runner.run(_loop_scenario(5))

    # Mock: lỗi (thường là bug kịch bản, không phải máy hỏng thật) KHÔNG chặn
    # việc soạn/thử kịch bản -> vẫn chạy hết toàn bộ vòng lặp.
    device_results = [r for r in results if r.action == "measure_frequency"]
    assert len(device_results) == 5
    assert all(not r.ok for r in device_results)
    assert runner.stop_reason == ""


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


# ---------------------------------------------------------------------------
# result_cell(): chuỗi gọn cho cột Kết quả trên grid
# ---------------------------------------------------------------------------

def test_result_cell_write_is_empty():
    # lệnh ghi (không query) -> TRỐNG (cột Trạng thái đã báo OK), không trùng lặp.
    r = StepResult(action="raw_scpi", device_key="SMW200A",
                   text="SOUR1:FREQ:CW 1000000000 HZ", is_query=False)
    assert r.result_cell() == ""


def test_result_cell_query_numeric():
    r = StepResult(action="raw_scpi", device_key="CNT91",
                   value=1e11, unit="Hz", is_query=True)
    assert r.result_cell() == "100.000.000.000 Hz"


def test_result_cell_query_string():
    r = StepResult(action="raw_scpi", device_key="SMW200A",
                   text="INT", is_query=True)
    assert r.result_cell() == "INT"


def test_result_cell_error():
    r = StepResult(action="raw_scpi", device_key="CNT91",
                   ok=False, error="Timeout")
    assert r.result_cell() == "LỖI — Timeout"


# ---------------------------------------------------------------------------
# enumerate_nodes() / StepResult.flat_index — đối chiếu vị trí node giữa
# 2 object graph độc lập cùng nội dung (Bước 2 vs Scenario Builder mở cùng file).
# ---------------------------------------------------------------------------

def _nested_scenario() -> Scenario:
    """Loop lồng If — cấu trúc đủ phức tạp để kiểm tra thứ tự DFS."""
    return Scenario(name="Lồng nhau", nodes=[
        ScenarioStep(action="identify", devices=["CNT91"]),
        LoopBlock(count=2, body=[
            ScenarioStep(action="measure_frequency", devices=["CNT91"]),
            IfBlock(branches=[
                Branch(condition=Condition(kind="measure", op=">", value=1e6),
                       body=[ScenarioStep(action="identify", devices=["CNT91"])]),
                Branch(condition=None, body=[
                    ScenarioStep(action="identify", devices=["N1913A"]),
                    ScenarioStep(action="wait", devices=[], params={"seconds": 0.0}),
                ]),
            ]),
        ]),
        ScenarioStep(action="measure_power", devices=["N1913A"]),
    ])


def test_enumerate_nodes_order_and_kinds():
    scn = _nested_scenario()
    flat = enumerate_nodes(scn.nodes)
    kinds = [node_kind(n) for n in flat]
    # step, loop, step(trong loop), if, step(nhánh1), step(nhánh else)x2, step cuối
    assert kinds == ["step", "loop", "step", "if", "step", "step", "step", "step"]
    assert flat[0] is scn.nodes[0]
    assert flat[1] is scn.nodes[1]                       # LoopBlock
    assert flat[-1] is scn.nodes[2]                       # step cuối cùng cấp ngoài


def test_enumerate_nodes_stable_across_independent_loads():
    scn = _nested_scenario()
    d = scn.to_dict()
    a = Scenario.from_dict(d)
    b = Scenario.from_dict(d)
    flat_a = enumerate_nodes(a.nodes)
    flat_b = enumerate_nodes(b.nodes)
    assert len(flat_a) == len(flat_b)
    for na, nb in zip(flat_a, flat_b):
        assert id(na) != id(nb)                           # object graph khác nhau
        assert node_kind(na) == node_kind(nb)
        if isinstance(na, ScenarioStep):
            assert na.action == nb.action
            assert na.devices == nb.devices


def test_flat_index_stamped_matches_enumerate_nodes():
    scn = _nested_scenario()
    results = ScenarioRunner(mock=True, settle_wait=False).run(scn)
    flat = enumerate_nodes(scn.nodes)
    for r in results:
        assert r.flat_index != -1
        assert flat[r.flat_index] is not None


def test_flat_index_cross_reference_between_independent_loads(tmp_path):
    """Mô phỏng đúng tình huống thật: Bước 2 và Scenario Builder mở CÙNG 1
    file .json bằng 2 lần Scenario.load_json() độc lập -> id() khác nhau
    nhưng flat_index phải tra đúng node tương ứng ở phía kia."""
    scn = _nested_scenario()
    p = tmp_path / "nested.json"
    scn.save_json(p)

    scn_a = Scenario.load_json(p)   # phía "worker" chạy kịch bản
    scn_b = Scenario.load_json(p)   # phía "Scenario Builder" hiển thị cây

    results = ScenarioRunner(mock=True, settle_wait=False).run(scn_a)
    flat_b = enumerate_nodes(scn_b.nodes)

    for r in results:
        if r.kind != "step":
            continue
        node_b = flat_b[r.flat_index]
        assert isinstance(node_b, ScenarioStep)
        assert node_b.action == r.action
        if r.device_key:
            assert r.device_key in node_b.devices
