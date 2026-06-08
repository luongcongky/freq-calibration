"""
unit_test/conftest.py
=====================
Cấu hình chung cho pytest:
  - Thêm project root vào sys.path để import được package `drivers`.
  - Tùy chọn dòng lệnh:
        --real            : chạy với PHẦN CỨNG THẬT (mặc định: mock).
        --addr-file PATH  : file JSON map {model_key: "VISA address"} cho chế độ real.

Mặc định mọi test chạy ở MOCK (không cần phần cứng). Khi có thiết bị thật:
    pytest unit_test --real --addr-file unit_test/addresses.json
"""

import sys
import json
from pathlib import Path

import pytest

# Cho phép import `drivers`, `core`, ... từ project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# test_connectivity.py là SCRIPT CLI (chạy: python unit_test/test_connectivity.py
# --mock), không phải module pytest — các hàm test_*(inst) trong đó là helper nhận
# tham số, sẽ bị pytest gom nhầm. Loại khỏi quá trình thu thập của pytest.
collect_ignore = ["test_connectivity.py"]


def pytest_addoption(parser):
    parser.addoption(
        "--real", action="store_true", default=False,
        help="Chạy test với phần cứng thật (mặc định: mock).",
    )
    parser.addoption(
        "--addr-file", action="store", default=None,
        help="Đường dẫn file JSON map model_key -> VISA address (cho --real).",
    )


@pytest.fixture(scope="session")
def use_mock(request) -> bool:
    """True nếu chạy mock (mặc định), False nếu --real."""
    return not request.config.getoption("--real")


@pytest.fixture(scope="session")
def address_map(request) -> dict:
    """Đọc map model_key -> VISA address từ --addr-file (rỗng nếu không có)."""
    path = request.config.getoption("--addr-file")
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise pytest.UsageError("--addr-file phải là JSON object {model: address}.")
    return data
