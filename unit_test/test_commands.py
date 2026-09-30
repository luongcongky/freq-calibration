"""
unit_test/test_commands.py
=============================
Test core/commands.py::parse_cmd() + Cmd.force_query (REG-03 —
test_reports/2026-10-01_regression/BAO_CAO_TEST_LAI.md):

Lệnh native của 1 số thiết bị (vd Boonton 4231A: MFS, TM0, TM1) vẫn trả kết
quả về dù KHÔNG kết thúc bằng "?" theo quy ước SCPI thường — parse_cmd()
trước đây chỉ xét "?" nên is_query luôn False cho các lệnh này, scenario_runner
chỉ GHI lệnh, không đọc phản hồi -> ô Kết quả trống. Cmd.force_query cho
phép đánh dấu tay qua checkbox "Lệnh đọc kết quả (query)" (gui/
command_reference.py::_CmdEditorDialog).
"""

from core.commands import Cmd, parse_cmd


def test_parse_cmd_is_query_true_when_ends_with_question_mark():
    _, _, is_query = parse_cmd(Cmd("MEAS?", "Đo"))
    assert is_query is True


def test_parse_cmd_is_query_false_for_plain_write_command():
    _, _, is_query = parse_cmd(Cmd("SENS:FREQ 1E9", "Đặt tần số"))
    assert is_query is False


def test_parse_cmd_force_query_overrides_missing_question_mark():
    """MFS/TM0/TM1 (Boonton 4231A) — không có "?" nhưng vẫn trả kết quả."""
    _, _, is_query = parse_cmd(Cmd("MFS", "Đọc tần số đo được", force_query=True))
    assert is_query is True


def test_parse_cmd_force_query_default_false_does_not_change_old_behavior():
    """Lệnh cũ trong data/custom_commands.json (lưu trước khi có field này)
    nạp lại qua Cmd(**r) vẫn dùng default force_query=False — không đổi
    hành vi is_query đã lưu/hiển thị từ trước."""
    cmd = Cmd(**{"cmd": "SENS:FREQ 1E9", "desc": "Đặt tần số"})
    assert cmd.force_query is False
    _, _, is_query = parse_cmd(cmd)
    assert is_query is False


def test_custom_command_json_roundtrip_preserves_force_query():
    from gui.command_reference import _cmds_from_json, _cmds_to_json

    cmds = [Cmd("MFS", "Đọc tần số đo được", force_query=True),
            Cmd("TM0", "Chọn chế độ đo 0", force_query=False)]
    rows = _cmds_to_json(cmds)
    assert rows[0]["force_query"] is True
    assert rows[1]["force_query"] is False

    restored = _cmds_from_json(rows)
    assert restored[0].force_query is True
    assert restored[1].force_query is False


def test_custom_command_json_without_force_query_key_defaults_false():
    """Round-trip với dữ liệu CŨ (chưa có key "force_query" trong JSON đã
    lưu trước khi nâng cấp) — không được crash, mặc định False."""
    from gui.command_reference import _cmds_from_json

    restored = _cmds_from_json([{"cmd": "TM1", "desc": "Chọn chế độ đo 1", "note": ""}])
    assert restored[0].force_query is False
