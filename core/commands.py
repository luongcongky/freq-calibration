"""
core/commands.py
================
Tập lệnh SCPI theo dòng máy — nguồn dữ liệu dùng chung cho:
  - gui/command_reference.py   (màn hình Tập lệnh)
  - gui/scenario_grid.py       (StepEditorDialog — soạn bước)
  - core/scenario_runner.py    (thực thi lệnh thô raw_scpi)

Hàm parse_cmd() tự phát hiện tham số từ cú pháp lệnh:
  <param_name>   → ô nhập liệu
  WORD|WORD|...  → dropdown lựa chọn
  Lệnh kết thúc bằng ?  → query mode (trả kết quả về log)
"""

from __future__ import annotations

import re
import sys
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Kiểu dữ liệu
# ---------------------------------------------------------------------------

@dataclass
class Cmd:
    cmd: str        # cú pháp lệnh SCPI, ví dụ "SOUR<ch>:FREQ:CW <Hz> HZ"
    desc: str       # mô tả tiếng Việt
    note: str = ""  # ghi chú (dải tham số, ví dụ, cảnh báo…)


@dataclass
class ParsedParam:
    name: str                                    # tên placeholder trong template
    label: str                                   # nhãn hiển thị cho user
    ptype: str                                   # "int" | "float" | "enum"
    default: Any                                 # giá trị mặc định
    unit: str = ""                               # đơn vị (chỉ dùng int/float)
    choices: list = field(default_factory=list)  # giá trị cho enum


# ---------------------------------------------------------------------------
# Lệnh chung IEEE 488.2
# ---------------------------------------------------------------------------

COMMON_COMMANDS: list[Cmd] = [
    Cmd("*IDN?",  "Nhận diện thiết bị",
        "Trả chuỗi: Vendor,Model,Serial,Firmware"),
    Cmd("*CLS",   "Xóa thanh ghi trạng thái và hàng đợi lỗi SCPI"),
    Cmd("*RST",   "Reset thiết bị về cài đặt mặc định nhà máy"),
    Cmd("*TST?",  "Tự kiểm tra nội bộ",
        "Trả 0 = OK; khác 0 = lỗi phần cứng"),
    Cmd("*OPC",   "Đặt bit Operation Complete khi hoàn tất tất cả thao tác"),
    Cmd("*OPC?",  "Trả '1' khi tất cả thao tác đã hoàn tất (blocking)"),
]

# Pseudo-command hiển thị trong StepEditorDialog để tạo bước "wait"
WAIT_CMD = Cmd("WAIT <seconds>", "Chờ ổn định",
               "Tạm dừng kịch bản  |  Ví dụ: WAIT 0.5")

# ---------------------------------------------------------------------------
# Tập lệnh riêng theo nhóm driver
# ---------------------------------------------------------------------------

_PENDULUM_CMDS: list[Cmd] = [
    Cmd("SENS:ACQ:APER <s>",
        "Đặt thời gian gate/aperture đo tần số",
        "Dải: 100 µs – 1000 s  |  Ví dụ: SENS:ACQ:APER 1.0"),
    Cmd("SENS:ACQ:APER?",
        "Đọc thời gian gate/aperture hiện tại (giây)"),
    Cmd("MEAS:FREQ? (@<ch>)",
        "Trigger & đọc tần số kênh chỉ định (Hz)",
        "Ví dụ: MEAS:FREQ? (@1)"),
    Cmd("SENS:ROSC:SOUR INT|EXT",
        "Chọn nguồn tham chiếu: INT = nội  /  EXT = ngoài"),
    Cmd("SENS:ROSC:SOUR?",
        "Đọc nguồn tham chiếu hiện tại"),
    Cmd("SENS:ROSC:EXT:FREQ <Hz>",
        "Đặt tần số nguồn tham chiếu ngoài",
        "Thường 10 000 000 (10 MHz)"),
]

_PM6680_CMDS: list[Cmd] = [
    Cmd("SENS:ACQ:APER <s>",
        "Đặt thời gian gate (chế độ SCPI)",
        "Hoặc: TA <s>  nếu dùng legacy Philips"),
    Cmd("SENS:ACQ:APER?",
        "Đọc thời gian gate hiện tại"),
    Cmd("MEAS:FREQ? (@<ch>)",
        "Trigger & đọc tần số kênh (chế độ SCPI)"),
    Cmd("FREQ A",
        "Chọn hàm đo tần số kênh A  [legacy Philips]",
        "Chỉ dùng khi USE_LEGACY_SYNTAX = True"),
    Cmd("X",
        "Kích hoạt & đọc kết quả  [legacy Philips]",
        "Chỉ dùng khi USE_LEGACY_SYNTAX = True"),
    Cmd("TA <s>",
        "Đặt measurement time  [legacy Philips]",
        "Ví dụ: TA 1.000000"),
]

_KS53131_CMDS: list[Cmd] = [
    Cmd("FREQ:ARM:STOP:SOUR TIM",
        "Chọn nguồn kết thúc ARM là Timer",
        "Phải gửi TRƯỚC lệnh đặt gate time"),
    Cmd("FREQ:ARM:STOP:TIM <s>",
        "Đặt thời gian gate đo tần số",
        "Dải: 1 ms – 1000 s"),
    Cmd("FREQ:ARM:STOP:TIM?",
        "Đọc thời gian gate hiện tại (giây)"),
    Cmd("MEAS:FREQ? (@<ch>)",
        "Trigger & đọc tần số kênh chỉ định (Hz)"),
]

_KS53220_CMDS: list[Cmd] = [
    Cmd("SENS:FREQ:GATE:TIME <s>",
        "Đặt thời gian gate đo tần số",
        "Dải: 1 ms – 1000 s"),
    Cmd("SENS:FREQ:GATE:TIME?",
        "Đọc thời gian gate hiện tại (giây)"),
    Cmd("MEAS:FREQ? (@<ch>)",
        "Trigger & đọc tần số kênh chỉ định (Hz)"),
    Cmd("CONF:FREQ",
        "Cấu hình chế độ đo tần số"),
    Cmd("INIT",
        "Kích hoạt đo (không chờ kết quả)"),
    Cmd("READ?",
        "Kích hoạt & đọc kết quả đo"),
    Cmd("FETCH?",
        "Lấy kết quả lần đo gần nhất (không trigger mới)"),
    Cmd("ABOR",
        "Hủy phép đo đang thực hiện"),
]

_KS531MW_CMDS: list[Cmd] = [
    Cmd("SENS:FREQ:GATE:TIME <s>",
        "Đặt thời gian gate/sample",
        "Dải: 1 ms – 1000 s"),
    Cmd("SENS:FREQ:GATE:TIME?",
        "Đọc thời gian gate hiện tại (giây)"),
    Cmd("MEAS:FREQ?",
        "Trigger & đọc tần số CW cao tần (Hz)",
        "Không có số kênh — 1 đầu vào duy nhất"),
]

_KS53147_CMDS: list[Cmd] = _KS531MW_CMDS + [
    Cmd("MEAS:SCAL:POW?",
        "Đo công suất tích hợp (dBm)",
        "Chỉ 53147A — có đầu đo công suất riêng"),
]

_KS_PWR_CMDS: list[Cmd] = [
    Cmd("SENS<ch>:FREQ <Hz>",
        "Đặt tần số tín hiệu để áp đúng cal factor đầu đo",
        "Ví dụ: SENS1:FREQ 1000000000"),
    Cmd("SENS<ch>:FREQ?",
        "Đọc tần số hiệu chỉnh kênh hiện tại (Hz)"),
    Cmd("UNIT<ch>:POW DBM",
        "Đặt đơn vị đọc về dBm"),
    Cmd("CAL<ch>:ZERO:AUTO ONCE",
        "Auto-zero đầu đo một lần",
        "Phải tháo tín hiệu RF trước khi zero"),
    Cmd("FETC<ch>?",
        "Đọc kết quả công suất hiện tại (dBm, không trigger)"),
    Cmd("READ<ch>?",
        "Trigger đo mới & đọc kết quả (dBm)"),
    Cmd("MEAS:POW:AC?",
        "Thực hiện đo công suất AC đầy đủ trình tự"),
]

_NRVD_CMDS: list[Cmd] = [
    Cmd("SENS<ch>:FREQ <Hz>",
        "Đặt tần số tín hiệu để áp đúng cal factor kênh",
        "Ví dụ: SENS1:FREQ 1000000000"),
    Cmd("SENS<ch>:FREQ?",
        "Đọc tần số hiệu chỉnh kênh (Hz)"),
    Cmd("UNIT:POW DBM",
        "Đặt đơn vị toàn cục về dBm"),
    Cmd("SENS<ch>:POW:UNIT DBM",
        "Đặt đơn vị kênh chỉ định về dBm"),
    Cmd("MEAS?",
        "Trigger & đọc công suất kênh mặc định (dBm)",
        "Trả 9.9E+37 nếu kết quả không hợp lệ"),
    Cmd("CAL<ch>:ZERO:AUTO ONCE",
        "Auto-zero đầu đo kênh chỉ định",
        "Phải tháo tín hiệu RF trước khi zero"),
    Cmd("SYST:ERR?",
        "Đọc một lỗi từ hàng đợi lỗi SCPI",
        "Trả: <code>,\"<mô tả>\"  |  0 = không lỗi"),
]

_SMW_CMDS: list[Cmd] = [
    Cmd("SOUR<ch>:FREQ:CW <Hz> HZ",
        "Đặt tần số CW kênh chỉ định",
        "Dải: 100 kHz – 20 GHz  |  Ví dụ: SOUR1:FREQ:CW 1000000000 HZ"),
    Cmd("SOUR<ch>:FREQ:CW?",
        "Đọc tần số CW hiện tại (Hz)"),
    Cmd("SOUR<ch>:FREQ:OFFS <Hz> HZ",
        "Đặt offset tần số (bù sai lệch cable/converter)"),
    Cmd("SOUR<ch>:POW:POW <dBm> dBm",
        "Đặt mức công suất RF output",
        "Dải: -130 – +30 dBm  |  Ví dụ: SOUR1:POW:POW -10 dBm"),
    Cmd("SOUR<ch>:POW:POW?",
        "Đọc mức công suất RF hiện tại (dBm)"),
    Cmd("SOUR<ch>:POW:OFFS <dB>",
        "Đặt offset công suất (bù suy hao cable/attenuator)"),
    Cmd("OUTP<ch>:STAT ON",
        "Bật RF output kênh chỉ định"),
    Cmd("OUTP<ch>:STAT OFF",
        "Tắt RF output kênh chỉ định"),
    Cmd("OUTP<ch>:STAT?",
        "Đọc trạng thái RF output kênh",
        "Trả: 1 = ON  /  0 = OFF"),
    Cmd("ROSC:SOUR INT",
        "Dùng nguồn tham chiếu 10 MHz nội"),
    Cmd("ROSC:SOUR EXT",
        "Khóa vào nguồn tham chiếu ngoài"),
    Cmd("ROSC:SOUR?",
        "Đọc nguồn tham chiếu hiện tại  (INT / EXT)"),
    Cmd("ROSC:EXT:FREQ <Hz> HZ",
        "Đặt tần số nguồn tham chiếu ngoài",
        "Thường 10000000 (10 MHz)"),
    Cmd("SOUR<ch>:AM:STAT ON|OFF",
        "Bật / tắt điều chế biên độ (AM)"),
    Cmd("SOUR<ch>:FM:STAT ON|OFF",
        "Bật / tắt điều chế tần số (FM)"),
    Cmd("SOUR<ch>:PM:STAT ON|OFF",
        "Bật / tắt điều chế pha (PM)"),
    Cmd("SOUR<ch>:IQ:STAT ON|OFF",
        "Bật / tắt điều chế vector IQ"),
    Cmd("SOUR<ch>:FREQ:STAR <Hz> HZ",
        "Tần số bắt đầu sweep"),
    Cmd("SOUR<ch>:FREQ:STOP <Hz> HZ",
        "Tần số kết thúc sweep"),
    Cmd("SOUR<ch>:SWE:FREQ:STEP:LIN <Hz> HZ",
        "Bước tần số sweep tuyến tính"),
    Cmd("SOUR<ch>:SWE:FREQ:DWEL <s> S",
        "Thời gian dừng tại mỗi bước sweep"),
    Cmd("SOUR<ch>:SWE:FREQ:MODE STEP",
        "Chế độ sweep từng bước (kích hoạt thủ công)"),
    Cmd("SOUR<ch>:SWE:FREQ:EXEC",
        "Tiến 1 bước trong sweep"),
    Cmd("SOUR<ch>:FREQ:MODE CW",
        "Chuyển về chế độ CW (thoát khỏi sweep)"),
    Cmd("SOUR<ch>:FREQ:MODE SWE",
        "Chuyển sang chế độ sweep"),
    Cmd("SYST:ERR?",
        "Đọc một lỗi từ hàng đợi lỗi SCPI",
        "Trả: <code>,\"<mô tả>\"  |  0,\"No Error\" = không lỗi"),
]

_R5372P_CMDS: list[Cmd] = [
    Cmd("E  [placeholder]",
        "Kích hoạt đo (mã trigger Advantest)",
        "TODO: xác nhận theo manual R5372P"),
    Cmd("?  [placeholder]",
        "Đọc kết quả đo tần số",
        "TODO: xác nhận theo manual R5372P"),
    Cmd("GA <val>  [placeholder]",
        "Đặt gate/resolution",
        "TODO: xác nhận theo manual R5372P"),
]

_BOONTON_CMDS: list[Cmd] = [
    Cmd("FR <Hz> HZ  [placeholder]",
        "Đặt tần số tín hiệu để chọn cal factor",
        "TODO: xác nhận theo manual Boonton 4231A"),
    Cmd("DM  [placeholder]",
        "Chọn đơn vị hiển thị dBm",
        "TODO: xác nhận theo manual"),
    Cmd("TR  [placeholder]",
        "Trigger đo & đọc kết quả công suất",
        "TODO: xác nhận theo manual"),
    Cmd("ZE  [placeholder]",
        "Zero đầu đo công suất",
        "TODO: xác nhận theo manual"),
]

DEVICE_COMMANDS: dict[str, list[Cmd]] = {
    "SMW200A": _SMW_CMDS,
    "CNT85":   _PENDULUM_CMDS,
    "CNT90":   _PENDULUM_CMDS,
    "CNT91":   _PENDULUM_CMDS,
    "53131A":  _KS53131_CMDS,
    "53132A":  _KS53131_CMDS,
    "53220A":  _KS53220_CMDS,
    "53150A":  _KS531MW_CMDS,
    "53151A":  _KS531MW_CMDS,
    "53147A":  _KS53147_CMDS,
    "PM6680":  _PM6680_CMDS,
    "PM6690":  _PENDULUM_CMDS,
    "R5372P":  _R5372P_CMDS,
    "E4410A":  _KS_PWR_CMDS,
    "E4418A":  _KS_PWR_CMDS,
    "N1911A":  _KS_PWR_CMDS,
    "N1913A":  _KS_PWR_CMDS,
    "N1914A":  _KS_PWR_CMDS,
    "4231A":   _BOONTON_CMDS,
    "NRVD":    _NRVD_CMDS,
}

# ---------------------------------------------------------------------------
# Parse cú pháp lệnh → template + params + is_query
# ---------------------------------------------------------------------------

# <param_name> → ô nhập liệu
_BRACKET_RE = re.compile(r'<([^>]+)>')

# WORD|WORD|... (không nằm trong <>) → dropdown
_ENUM_RE = re.compile(r'(?<![<\w])([A-Z]{2,}(?:\|[A-Z]{2,})+)(?![>\w])')

# Thông tin gợi ý cho các tên param phổ biến
_PARAM_META: dict[str, tuple] = {
    # name → (label_vi, ptype, default, unit)
    "ch":      ("Kênh",          "int",   1,      ""),
    "Hz":      ("Tần số",        "float", 1e9,    "Hz"),
    "s":       ("Thời gian",     "float", 1.0,    "s"),
    "seconds": ("Thời gian chờ", "float", 0.5,    "s"),
    "dBm":     ("Công suất",     "float", -10.0,  "dBm"),
    "dB":      ("Offset",        "float", 0.0,    "dB"),
    "val":     ("Giá trị",       "float", 0.0,    ""),
    "freq_hz": ("Tần số RF",     "float", 1e9,    "Hz"),
    "offset":  ("Offset",        "float", 0.0,    ""),
}


def parse_cmd(cmd: Cmd) -> tuple[str, list[ParsedParam], bool]:
    """
    Phân tích cú pháp lệnh, trả về (template, params, is_query).

    template  — chuỗi dùng với str.format(**values) để tạo lệnh thực thi
    params    — danh sách ParsedParam (rỗng nếu lệnh không có tham số)
    is_query  — True nếu lệnh kết thúc bằng ?

    Ví dụ:
      "SOUR<ch>:FREQ:CW <Hz> HZ"
          → ("SOUR{ch}:FREQ:CW {Hz} HZ",
             [ParsedParam("ch","Kênh","int",1), ParsedParam("Hz","Tần số","float",1e9,"Hz")],
             False)
      "MEAS?"  →  ("MEAS?", [], True)
      "SENS:ROSC:SOUR INT|EXT"
          → ("SENS:ROSC:SOUR {choice}",
             [ParsedParam("choice","Chọn","enum","INT",choices=["INT","EXT"])],
             False)
    """
    raw = cmd.cmd
    template = raw
    params: list[ParsedParam] = []
    seen: set[str] = set()

    # Pass 1: <param> placeholders
    for m in _BRACKET_RE.finditer(raw):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        meta = _PARAM_META.get(name)
        if meta:
            label, ptype, default, unit = meta
        else:
            label = name
            ptype = "int" if name.lower() in ("ch", "n", "i") else "float"
            default = 1 if ptype == "int" else 0.0
            unit = ""
        params.append(ParsedParam(name=name, label=label, ptype=ptype,
                                  default=default, unit=unit))
        template = template.replace(f"<{name}>", f"{{{name}}}")

    # Pass 2: ENUM patterns
    for m in _ENUM_RE.finditer(raw):
        enum_str = m.group(1)
        choices = enum_str.split("|")
        base = "choice"
        name = base
        idx = 2
        while name in seen:
            name = f"{base}{idx}"; idx += 1
        seen.add(name)
        params.append(ParsedParam(name=name, label="Chọn", ptype="enum",
                                  default=choices[0], choices=choices))
        template = template.replace(enum_str, f"{{{name}}}")

    is_query = "?" in raw   # ? anywhere marks a SCPI query, even inside parentheses
    return template, params, is_query


# ---------------------------------------------------------------------------
# Truy cập lệnh (có hỗ trợ custom override từ data/custom_commands.json)
# ---------------------------------------------------------------------------

# Khi chạy bản đóng gói (PyInstaller, sys.frozen=True): ghi cạnh file .exe để tùy
# chỉnh được lưu lâu dài. Khi chạy từ source: ghi ở gốc project như cũ.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent.parent
CUSTOM_DATA_PATH = _BASE_DIR / "data" / "custom_commands.json"


def load_custom() -> dict[str, list[dict]]:
    if CUSTOM_DATA_PATH.exists():
        try:
            with open(CUSTOM_DATA_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_common_commands(custom: dict | None = None) -> list[Cmd]:
    """Trả lệnh chung (có thể bị override bởi custom['__common__'])."""
    if custom is None:
        custom = load_custom()
    if "__common__" in custom:
        return [Cmd(**r) for r in custom["__common__"]]
    return list(COMMON_COMMANDS)


def get_commands_for(model_key: str, custom: dict | None = None) -> list[Cmd]:
    """Trả lệnh riêng của model_key (không gộp lệnh chung)."""
    if custom is None:
        custom = load_custom()
    if model_key in custom:
        return [Cmd(**r) for r in custom[model_key]]
    return list(DEVICE_COMMANDS.get(model_key, []))
