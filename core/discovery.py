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

import logging
from dataclasses import dataclass, field
from typing import Optional

from drivers import DEVICE_REGISTRY

log = logging.getLogger(__name__)


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
    addrs = addresses if addresses is not None else scan_resources(mock, visa_backend)
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
