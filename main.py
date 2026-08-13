import logging
import sys


def _run_identify_probe(argv: list[str]) -> None:
    """Chế độ nội bộ dùng bởi core/discovery.py._identify_subprocess() trong
    bản đóng gói: chạy *IDN?/PROBE_CMD trên MỘT địa chỉ VISA rồi in JSON ra
    stdout và thoát — KHÔNG mở GUI. Xem giải thích tại core/discovery.py.
    """
    import json
    try:
        # Bản đóng gói có --splash (xem freq-calibration.spec) tự bật splash
        # ngay khi tiến trình khởi động, kể cả tiến trình con này — đóng ngay
        # để không nhấp nháy 1 cửa sổ splash cho MỖI địa chỉ VISA được quét.
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass
    from core.discovery import identify_resource, _probe_identify

    address = argv[0]
    timeout_ms = int(argv[1]) if len(argv) > 1 else 2000
    visa_backend = argv[2] if len(argv) > 2 else ""

    idn = identify_resource(address, mock=False, timeout_ms=timeout_ms, visa_backend=visa_backend)
    if not idn:
        idn = _probe_identify(address, timeout_ms=timeout_ms, visa_backend=visa_backend)
    print(json.dumps(idn))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--identify-probe":
        _run_identify_probe(sys.argv[2:])
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    from gui.session_manager import run_session_manager
    run_session_manager()


if __name__ == "__main__":
    main()
