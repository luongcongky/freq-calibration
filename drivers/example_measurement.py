"""
example_measurement.py
======================
Đo kiểm tần số tự động:
  - Tự động scan toàn bộ VISA resources (GPIB local, TCPIP/VXI-11)
  - Nhận diện SMW200A và CNT-90XL qua *IDN?
  - Hỏi xác nhận trước khi đo
  - Xuất kết quả ra CSV

Hỗ trợ cả kết nối local GPIB lẫn remote qua Tailscale / VPN.
"""

import csv
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pyvisa

from drivers import SMW200A, CNT90XL

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SCAN CONFIG
# ---------------------------------------------------------------------------

# Nếu dùng remote qua Tailscale/VPN, thêm IP của máy trung gian vào đây.
# Để trống [] nếu chỉ dùng local GPIB.
REMOTE_HOSTS: list[str] = [
    # "100.64.0.5",   # ví dụ Tailscale IP của máy tại trung tâm
]

# Timeout khi thử kết nối từng resource (ms)
SCAN_TIMEOUT_MS = 3_000

# ---------------------------------------------------------------------------
# MEASUREMENT CONFIG
# ---------------------------------------------------------------------------
TEST_FREQUENCIES = [
    1e6,   10e6,  100e6,
    500e6, 1e9,   2e9,
    5e9,   10e9,
]

POWER_DBM   = -10.0
GATE_TIME_S = 1.0
N_SAMPLES   = 5
SETTLE_S    = 0.5
OUTPUT_DIR  = Path("results")

# ---------------------------------------------------------------------------
# Keyword fingerprints để nhận diện thiết bị qua *IDN?
# ---------------------------------------------------------------------------
SMW_KEYWORDS = ("SMW200", "SMW-200")
CNT_KEYWORDS = ("CNT-90", "CNT90", "PENDULUM")


# ---------------------------------------------------------------------------
# Data class cho kết quả scan
# ---------------------------------------------------------------------------
@dataclass
class FoundInstrument:
    address: str
    idn: str
    kind: str   # "SMW200A" | "CNT90XL" | "UNKNOWN"

    def __str__(self) -> str:
        return f"[{self.kind:10s}]  {self.address}\n              IDN: {self.idn.strip()}"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def _build_resource_list(rm: pyvisa.ResourceManager) -> list[str]:
    """
    Xây dựng danh sách địa chỉ VISA cần thử:
      1. Tất cả resources local (pyvisa list_resources)
      2. VXI-11 broadcast trên từng REMOTE_HOST
    """
    addresses: list[str] = []

    # --- Local resources ---
    try:
        local = list(rm.list_resources())   # e.g. ("GPIB0::28::INSTR", ...)
        addresses.extend(local)
        log.info("Local VISA resources found: %d", len(local))
        for a in local:
            log.debug("  %s", a)
    except Exception as exc:
        log.warning("Cannot list local resources: %s", exc)

    # --- Remote hosts (VXI-11 / TCPIP) ---
    for host in REMOTE_HOSTS:
        # Thử VXI-11 discovery trên host (pyvisa-py hỗ trợ)
        try:
            remote = list(rm.list_resources(f"TCPIP0::{host}::?*::INSTR"))
            addresses.extend(remote)
            log.info("Remote %s: %d resources", host, len(remote))
        except Exception:
            pass

        # Thêm fallback GPIB-over-TCPIP cho địa chỉ GPIB phổ biến
        for gpib_addr in range(1, 31):
            addresses.append(
                f"TCPIP0::{host}::gpib0,{gpib_addr}::INSTR"
            )

    # Deduplicate, giữ thứ tự
    seen: set[str] = set()
    unique: list[str] = []
    for a in addresses:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique


def _identify_resource(
    rm: pyvisa.ResourceManager, address: str
) -> Optional[FoundInstrument]:
    """
    Thử mở resource, gửi *IDN?, trả về FoundInstrument hoặc None nếu thất bại.
    """
    try:
        inst = rm.open_resource(address)
        inst.timeout = SCAN_TIMEOUT_MS
        inst.read_termination  = "\n"
        inst.write_termination = "\n"
        idn = inst.query("*IDN?").strip()
        inst.close()
    except Exception as exc:
        log.debug("  ✗ %s  → %s", address, exc)
        return None

    idn_upper = idn.upper()
    if any(k in idn_upper for k in SMW_KEYWORDS):
        kind = "SMW200A"
    elif any(k in idn_upper for k in CNT_KEYWORDS):
        kind = "CNT90XL"
    else:
        kind = "UNKNOWN"

    return FoundInstrument(address=address, idn=idn, kind=kind)


def scan_instruments() -> tuple[Optional[str], Optional[str]]:
    """
    Quét toàn bộ VISA resources, in kết quả, và trả về
    (smw_address, cnt_address). Nếu không tìm thấy sẽ trả về None.
    """
    print("\n" + "─" * 62)
    print("  Auto-scan VISA instruments …")
    print("─" * 62)

    rm = pyvisa.ResourceManager()
    addresses = _build_resource_list(rm)

    print(f"  Đang thử {len(addresses)} địa chỉ VISA "
          f"(timeout {SCAN_TIMEOUT_MS} ms/địa chỉ) …\n")

    found: list[FoundInstrument] = []
    for i, addr in enumerate(addresses, 1):
        # Progress indicator nhỏ gọn
        print(f"  [{i:>3}/{len(addresses)}] {addr[:52]:<52}", end="\r")
        result = _identify_resource(rm, addr)
        if result is not None:
            found.append(result)
            # In ngay khi tìm thấy để user thấy tiến trình
            print(f"\n  ✓ FOUND  {result}\n")

    rm.close()
    print()  # clear progress line

    # Tổng kết
    smw_candidates = [f for f in found if f.kind == "SMW200A"]
    cnt_candidates = [f for f in found if f.kind == "CNT90XL"]
    unknown        = [f for f in found if f.kind == "UNKNOWN"]

    print("─" * 62)
    print(f"  Kết quả scan: {len(found)} thiết bị phản hồi")
    if unknown:
        print(f"  (Thiết bị không nhận diện được: {len(unknown)})")
    print("─" * 62 + "\n")

    smw_address = _pick_instrument(smw_candidates, "SMW200A (Signal Generator)")
    cnt_address = _pick_instrument(cnt_candidates, "CNT-90XL (Frequency Counter)")

    return smw_address, cnt_address


def _pick_instrument(
    candidates: list[FoundInstrument], label: str
) -> Optional[str]:
    """
    Nếu có đúng 1 candidate → dùng luôn.
    Nếu có nhiều → hỏi user chọn.
    Nếu không có → hỏi user nhập tay.
    """
    if len(candidates) == 1:
        print(f"  {label}:")
        print(f"    → Sử dụng: {candidates[0].address}")
        return candidates[0].address

    if len(candidates) > 1:
        print(f"  {label}: Tìm thấy {len(candidates)} thiết bị, chọn một:")
        for i, c in enumerate(candidates, 1):
            print(f"    {i}. {c.address}")
            print(f"       {c.idn.strip()}")
        while True:
            try:
                choice = int(input("  Nhập số thứ tự: ").strip())
                if 1 <= choice <= len(candidates):
                    return candidates[choice - 1].address
            except (ValueError, KeyboardInterrupt):
                pass
            print("  Lựa chọn không hợp lệ.")

    # Không tìm thấy → cho phép nhập tay
    print(f"  {label}: Không tìm thấy tự động.")
    manual = input(
        f"  Nhập địa chỉ VISA thủ công (Enter để bỏ qua): "
    ).strip()
    return manual if manual else None


# ---------------------------------------------------------------------------
# Main calibration routine
# ---------------------------------------------------------------------------

def run_calibration(smw_address: str, cnt_address: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = OUTPUT_DIR / f"freq_cal_{timestamp}.csv"

    with (
        SMW200A(smw_address) as gen,
        CNT90XL(cnt_address) as counter,
    ):
        gen.set_reference_internal()
        gen.set_power(POWER_DBM)
        gen.rf_on()

        counter.set_reference_external(10e6)
        counter.configure_frequency(
            channel=1,
            gate_time=GATE_TIME_S,
            auto_trigger=True,
        )

        print(f"\n{'='*62}")
        print(f"  Generator : {gen.identify().strip()}")
        print(f"  Counter   : {counter.identify().strip()}")
        print(f"  Gate time : {GATE_TIME_S} s  |  Samples/point: {N_SAMPLES}")
        print(f"  Output    : {csv_path}")
        print(f"{'='*62}\n")

        results = []

        for freq_set in TEST_FREQUENCIES:
            gen.set_frequency(freq_set)
            time.sleep(SETTLE_S)

            stats = counter.measure_statistics(n_samples=N_SAMPLES, func="FREQ")

            error_hz  = stats.mean - freq_set
            error_ppm = (error_hz / freq_set) * 1e6

            results.append({
                "timestamp":      datetime.now().isoformat(),
                "set_freq_hz":    freq_set,
                "meas_mean_hz":   stats.mean,
                "meas_std_hz":    stats.std_dev,
                "error_hz":       error_hz,
                "error_ppm":      error_ppm,
                "uncertainty_hz": stats.uncertainty,
                "n_samples":      stats.n_samples,
            })

            print(
                f"  {freq_set/1e6:>10.3f} MHz → "
                f"mean={stats.mean/1e6:.9f} MHz  "
                f"err={error_hz:+.3f} Hz  "
                f"({error_ppm:+.4f} ppm)  "
                f"std={stats.std_dev:.3e} Hz"
            )

        gen.rf_off()

        fieldnames = list(results[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"\n✓ Kết quả đã lưu tại: {csv_path}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    smw_address, cnt_address = scan_instruments()

    if not smw_address or not cnt_address:
        missing = []
        if not smw_address:
            missing.append("SMW200A")
        if not cnt_address:
            missing.append("CNT-90XL")
        print(f"\n✗ Không đủ thiết bị để đo: thiếu {', '.join(missing)}. Thoát.\n")
        sys.exit(1)

    # Xác nhận trước khi đo
    print(f"\n  SMW200A  →  {smw_address}")
    print(f"  CNT-90XL →  {cnt_address}")
    confirm = input("\n  Bắt đầu đo kiểm? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("  Đã hủy.")
        sys.exit(0)

    run_calibration(smw_address, cnt_address)


if __name__ == "__main__":
    main()