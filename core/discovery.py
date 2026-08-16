"""
core/discovery.py
=================
Phát hiện & nhận diện thiết bị VISA — KHÔNG phụ thuộc Qt (test được bằng pytest).

Mục tiêu UX: người không chuyên KHÔNG phải gõ tay địa chỉ VISA. Quy trình:

  1. scan_resources()        -> liệt kê mọi địa chỉ VISA đang có (GPIB/USB/LAN).
  2. identify_resource(addr) -> hỏi *IDN? để máy tự khai báo model.
  3. match_driver(idn)       -> tự khớp với DEVICE_REGISTRY (dựa IDN_KEYWORDS).
  4. scan_and_identify()     -> gộp 1+2+3 thành danh sách DiscoveredDevice.

Cho máy đời cũ KHÔNG có *IDN? (Advantest R5372P, Boonton 4231A) hoặc khi có 2 máy
TRÙNG model: dùng "wizard cắm-từng-máy" — snapshot_resources() trước/sau, rồi
diff_new_resources() để biết địa chỉ nào VỪA xuất hiện chính là máy vừa cắm.

Chế độ mock: dùng MOCK_TOPOLOGY để demo/scan offline không cần phần cứng.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from drivers import DEVICE_REGISTRY

log = logging.getLogger(__name__)

_ROOT = str(Path(__file__).resolve().parent.parent)


# ---------------------------------------------------------------------------
# Topology giả lập cho chế độ mock (demo scan offline).
#   address -> model_key | None  (None = máy đời cũ không trả *IDN?)
# ---------------------------------------------------------------------------

MOCK_TOPOLOGY: dict[str, Optional[str]] = {
    "GPIB0::3::INSTR": "CNT91",
    "GPIB0::7::INSTR": "53131A",
    "USB0::0x0957::0x1707::MY12345678::INSTR": "N1913A",
    "TCPIP0::192.168.1.10::inst0::INSTR": "53220A",
    "GPIB0::13::INSTR": None,            # Advantest R5372P giả lập (không *IDN?)
    "GPIB0::21::INSTR": "NRVD",          # R&S NRVD power meter
    "GPIB0::28::INSTR": "SMW200A",       # R&S SMW200A signal generator
}


# ---------------------------------------------------------------------------
# Kết quả phát hiện
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredDevice:
    address: str
    idn: str = ""
    matched_key: Optional[str] = None    # model_key trong DEVICE_REGISTRY (None nếu chưa khớp)
    serial: str = ""
    error: str = ""

    @property
    def is_matched(self) -> bool:
        return self.matched_key is not None

    @property
    def vendor(self) -> str:
        if self.matched_key:
            return DEVICE_REGISTRY[self.matched_key]["vendor"]
        return ""

    def display_model(self) -> str:
        if self.matched_key:
            return self.matched_key
        if self.idn:
            return "(chưa khớp driver)"
        return "(không trả lời *IDN?)"


# ---------------------------------------------------------------------------
# Quét tài nguyên VISA
# ---------------------------------------------------------------------------

def scan_resources(mock: bool = False, visa_backend: str = "") -> list[str]:
    """Liệt kê mọi địa chỉ VISA. Mock -> trả MOCK_TOPOLOGY."""
    if mock:
        return list(MOCK_TOPOLOGY.keys())
    import pyvisa
    rm = pyvisa.ResourceManager(visa_backend) if visa_backend else pyvisa.ResourceManager()
    try:
        return list(rm.list_resources())
    finally:
        try:
            rm.close()
        except Exception:  # noqa: BLE001
            pass


def identify_resource(
    address: str,
    mock: bool = False,
    timeout_ms: int = 2000,
    visa_backend: str = "",
) -> str:
    """
    Hỏi *IDN? tại một địa chỉ. Trả chuỗi IDN (rỗng nếu máy không trả lời).

    CẢNH BÁO: gửi *IDN? "mù" vào máy lạ có thể gây treo/sai trạng thái với máy
    talk-only đời cũ -> dùng timeout NGẮN và nuốt lỗi (trả "").
    """
    if mock:
        key = MOCK_TOPOLOGY.get(address)
        if key is None:
            return ""        # mô phỏng máy không có *IDN?
        cls = DEVICE_REGISTRY[key]["cls"]
        with cls(f"MOCK::{address}", mock=True) as dev:
            return dev.identify()

    import pyvisa
    rm = pyvisa.ResourceManager(visa_backend) if visa_backend else pyvisa.ResourceManager()
    try:
        inst = rm.open_resource(address)
        inst.timeout = timeout_ms
        try:
            inst.read_termination = "\n"
            inst.write_termination = "\n"
            # USB-TMC cần Device Clear trước khi query (tránh VI_ERROR_NCIC)
            if address.startswith("USB"):
                try:
                    inst.clear()
                except Exception:
                    pass
            return inst.query("*IDN?").strip()
        finally:
            inst.close()
    except Exception as exc:  # noqa: BLE001
        log.info("identify_resource(%s): không có *IDN? (%s)", address, exc)
        return ""
    finally:
        try:
            rm.close()
        except Exception:  # noqa: BLE001
            pass


def match_driver(idn: str) -> Optional[str]:
    """Khớp chuỗi *IDN? với DEVICE_REGISTRY qua IDN_KEYWORDS. Trả model_key hoặc None."""
    if not idn:
        return None
    for key, entry in DEVICE_REGISTRY.items():
        keywords = getattr(entry["cls"], "IDN_KEYWORDS", ())
        if keywords and any(k in idn for k in keywords):
            return key
    return None


def _parse_serial(idn: str) -> str:
    """Lấy serial number từ trường thứ 3 của *IDN? (nếu có)."""
    parts = [p.strip() for p in idn.split(",")]
    return parts[2] if len(parts) >= 3 else ""


# Prefix VISA không cần quét — serial port gây timeout dài khi gửi *IDN? mù.
_SKIP_PREFIXES = ("ASRL",)


def scan_and_identify(
    mock: bool = False,
    visa_backend: str = "",
    timeout_ms: int = 2000,
    addresses: Optional[list[str]] = None,
) -> list[DiscoveredDevice]:
    """
    Quét + hỏi *IDN? + tự khớp driver cho từng địa chỉ.

    addresses : nếu cho sẵn thì chỉ nhận diện các địa chỉ này (vd kết quả wizard),
                ngược lại tự scan toàn bộ.
    """
    all_addrs = addresses if addresses is not None else scan_resources(mock, visa_backend)
    addrs = [a for a in all_addrs if not any(a.startswith(p) for p in _SKIP_PREFIXES)]
    skipped = len(all_addrs) - len(addrs)
    if skipped:
        log.debug("Bỏ qua %d địa chỉ serial (ASRL) — không phải thiết bị đo lường.", skipped)
    out: list[DiscoveredDevice] = []
    for addr in addrs:
        idn = identify_resource(addr, mock=mock, timeout_ms=timeout_ms, visa_backend=visa_backend)
        out.append(DiscoveredDevice(
            address=addr,
            idn=idn,
            matched_key=match_driver(idn),
            serial=_parse_serial(idn),
        ))
    return out


# ---------------------------------------------------------------------------
# Wizard "cắm-từng-máy": phát hiện địa chỉ MỚI xuất hiện
# ---------------------------------------------------------------------------

def snapshot_resources(mock: bool = False, visa_backend: str = "") -> set[str]:
    """Chụp tập địa chỉ hiện có (để so sánh trước/sau khi cắm máy)."""
    return set(scan_resources(mock, visa_backend))


def diff_new_resources(before: set[str], after: set[str]) -> list[str]:
    """Trả các địa chỉ có trong 'after' nhưng không có trong 'before' (máy vừa cắm)."""
    return sorted(after - before)


# ---------------------------------------------------------------------------
# Kiểm tra kết nối với một driver cụ thể
# ---------------------------------------------------------------------------

@dataclass
class ConnectionTest:
    ok: bool
    model: str = ""
    idn: str = ""
    error: str = ""


def test_connection(model_key: str, address: str, mock: bool = False) -> ConnectionTest:
    """Mở driver model_key tại address, thử identify(), rồi đóng. Báo OK/lỗi."""
    if model_key not in DEVICE_REGISTRY:
        return ConnectionTest(ok=False, error=f"Model không có trong registry: {model_key}")
    cls = DEVICE_REGISTRY[model_key]["cls"]
    try:
        with cls(address if not mock else f"MOCK::{address}", mock=mock) as dev:
            return ConnectionTest(ok=True, model=dev.get_model(), idn=dev.identify())
    except Exception as exc:  # noqa: BLE001
        return ConnectionTest(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# Subprocess-safe scan — cách ly crash NI-VISA
# ---------------------------------------------------------------------------

def _probe_identify(
    address: str,
    timeout_ms: int = 2000,
    visa_backend: str = "",
) -> str:
    """
    Thử nhận diện thiết bị bằng PROBE_CMD khi *IDN? không phản hồi.

    Duyệt qua tất cả driver có thuộc tính PROBE_CMD. Nếu thiết bị phản hồi
    hợp lệ (số thực), trả PROBE_SYNTHETIC_IDN để match_driver() khớp về sau.

    Dùng cho thiết bị legacy (vd Pendulum CNT-90 ở chế độ local/locked)
    hoặc thiết bị hoàn toàn không có *IDN? (Advantest R5372P, Boonton 4231A).
    """
    import pyvisa
    candidates: list[tuple[str, str, str]] = []  # (model_key, probe_cmd, synthetic_idn)
    for key, entry in DEVICE_REGISTRY.items():
        cls = entry["cls"]
        probe_cmd = getattr(cls, "PROBE_CMD", None)
        synthetic_idn = getattr(cls, "PROBE_SYNTHETIC_IDN", None)
        if probe_cmd and synthetic_idn:
            candidates.append((key, probe_cmd, synthetic_idn))
    if not candidates:
        return ""
    rm = pyvisa.ResourceManager(visa_backend) if visa_backend else pyvisa.ResourceManager()
    try:
        inst = rm.open_resource(address)
        inst.timeout = timeout_ms
        inst.read_termination = "\n"
        inst.write_termination = "\n"
        try:
            for key, probe_cmd, synthetic_idn in candidates:
                try:
                    resp = inst.query(probe_cmd).strip()
                    float(resp)  # Phản hồi phải là số thực hợp lệ
                    log.info("probe_identify(%s): %s phản hồi %s -> '%s'",
                             address, key, probe_cmd, resp)
                    return synthetic_idn
                except Exception:  # noqa: BLE001
                    continue
        finally:
            try:
                inst.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        log.debug("probe_identify(%s): open_resource thất bại: %s", address, exc)
    finally:
        try:
            rm.close()
        except Exception:  # noqa: BLE001
            pass
    return ""


def _identify_subprocess(
    address: str,
    timeout_ms: int = 2000,
    visa_backend: str = "",
) -> str:
    """
    Chạy identify_resource (+ probe fallback) trong subprocess riêng biệt.

    Một số thiết bị GPIB khiến NI-VISA crash ngay tại viOpen() với "access
    violation reading 0x0" — lỗi tầng native DLL, KHÔNG thể catch bằng Python.
    Nếu chạy trong cùng process, toàn bộ app chết. Subprocess riêng đảm bảo:
    subprocess chết, app chính sống.

    Thứ tự thử: *IDN? → PROBE_CMD fallback.
    Trả "" nếu cả hai đều thất bại hoặc subprocess crash/timeout.

    LƯU Ý bản đóng gói (PyInstaller, sys.frozen=True): sys.executable lúc đó
    trỏ vào chính freq-calibration.exe, KHÔNG phải python.exe, nên không thể
    gọi "sys.executable -c <code>" (sẽ chỉ mở thêm một cửa sổ app mới thay vì
    chạy đoạn code). Thay vào đó gọi lại chính .exe với cờ nội bộ
    --identify-probe (xử lý trong main.py, không mở GUI) để vẫn giữ được cô
    lập tiến trình.
    """
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--identify-probe", address, str(timeout_ms), visa_backend]
    else:
        code = (
            f"import sys; sys.path.insert(0, {_ROOT!r})\n"
            "from core.discovery import identify_resource, _probe_identify\n"
            "import json\n"
            f"addr = {address!r}\n"
            f"idn = identify_resource(addr, mock=False,"
            f" timeout_ms={timeout_ms}, visa_backend={visa_backend!r})\n"
            f"if not idn:\n"
            f"    idn = _probe_identify(addr,"
            f" timeout_ms={timeout_ms}, visa_backend={visa_backend!r})\n"
            "print(json.dumps(idn))\n"
        )
        cmd = [sys.executable, "-c", code]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000 + 8,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except Exception:  # noqa: BLE001
        pass
    return ""


def scan_and_identify_safe(
    visa_backend: str = "",
    timeout_ms: int = 2000,
    max_workers: int = 4,
    existing_profile: "Optional[object]" = None,
) -> list[DiscoveredDevice]:
    """
    Quét + nhận diện toàn bộ địa chỉ VISA — crash-safe (subprocess per addr).

    existing_profile : ConnectionProfile — nếu cho vào, các thiết bị đã có
        trong profile nhưng không phản hồi *IDN? (vd CNT-90) vẫn được giữ lại
        trong kết quả (với address từ profile, idn="" và matched_key từ profile).
    """
    all_addrs = scan_resources(mock=False, visa_backend=visa_backend)
    addrs = [a for a in all_addrs if not any(a.startswith(p) for p in _SKIP_PREFIXES)]
    skipped = len(all_addrs) - len(addrs)
    if skipped:
        log.debug("Bỏ qua %d địa chỉ serial (ASRL).", skipped)

    def _identify_one(addr: str) -> DiscoveredDevice:
        idn = _identify_subprocess(addr, timeout_ms, visa_backend)
        return DiscoveredDevice(
            address=addr,
            idn=idn,
            matched_key=match_driver(idn),
            serial=_parse_serial(idn),
        )

    found: list[DiscoveredDevice] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_identify_one, a): a for a in addrs}
        for fut in as_completed(futures):
            try:
                found.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log.warning("scan_and_identify_safe: lỗi addr %s: %s",
                            futures[fut], exc)

    found.sort(key=lambda d: d.address)

    # Áp model từ profile cho thiết bị scan thấy địa chỉ nhưng không trả *IDN?
    # VD: CNT-90 ở GPIB1::10 — list_resources() thấy nó, subprocess crash khi
    # open_resource → idn="" → matched_key=None. Profile biết đó là CNT90.
    if existing_profile is not None:
        found_by_addr: dict[str, DiscoveredDevice] = {d.address: d for d in found}
        extra: list[DiscoveredDevice] = []
        for entry in getattr(existing_profile, "entries", []):
            scan_dev = found_by_addr.get(entry.address)
            if scan_dev is None:
                # Địa chỉ không xuất hiện trong scan → thiết bị đang tắt / ngắt kết nối,
                # không thêm vào kết quả để tránh hiển thị thiết bị không connect.
                log.info("Bỏ qua từ profile (không thấy trong scan): %s → %s",
                         entry.model_key, entry.address)
            elif scan_dev.matched_key is None:
                # Địa chỉ thấy nhưng không match được IDN → dùng model_key từ profile
                found.remove(scan_dev)
                extra.append(DiscoveredDevice(
                    address=entry.address,
                    idn="",
                    matched_key=entry.model_key,
                    serial=entry.serial,
                    error="không phản hồi *IDN? — model gán từ profile",
                ))
                log.info("Gán từ profile (không *IDN?): %s → %s",
                         entry.model_key, entry.address)
            # else: scan match được IDN → kết quả scan thắng (địa chỉ/serial mới nhất)
        found.extend(extra)
        found.sort(key=lambda d: d.address)

    return found
