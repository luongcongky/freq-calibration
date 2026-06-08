"""
unit_test/test_discovery.py
===========================
Test logic phát hiện/nhận diện thiết bị (core/discovery.py) và profile kết nối
(core/profile.py) ở chế độ MOCK — không cần phần cứng, không Qt.
"""

import pytest

from core.discovery import (
    scan_resources, identify_resource, match_driver, scan_and_identify,
    snapshot_resources, diff_new_resources,
    test_connection as check_connection,   # alias: tránh pytest gom nhầm thành test
    MOCK_TOPOLOGY, DiscoveredDevice,
)
from core.profile import ConnectionProfile, ProfileEntry


# ---------------------------------------------------------------------------
# match_driver
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("idn,expected", [
    ("HEWLETT-PACKARD,53131A,0,3944", "53131A"),
    ("Agilent Technologies,53220A,MY50000001,2.10", "53220A"),
    ("Keysight Technologies,N1913A,MY2,A1", "N1913A"),
    ("Pendulum Instruments,CNT-91,789012,V2.10", "CNT91"),
    ("Fluke,PM6690,901234,V1.30", "PM6690"),
    ("", None),
    ("Some,Unknown,Box,1.0", None),
])
def test_match_driver(idn, expected):
    assert match_driver(idn) == expected


# ---------------------------------------------------------------------------
# scan + identify (mock)
# ---------------------------------------------------------------------------

def test_scan_resources_mock():
    addrs = scan_resources(mock=True)
    assert set(addrs) == set(MOCK_TOPOLOGY.keys())


def test_identify_resource_mock():
    # Địa chỉ có model -> trả IDN khớp; địa chỉ legacy (None) -> rỗng.
    assert "CNT-91" in identify_resource("GPIB0::3::INSTR", mock=True)
    assert identify_resource("GPIB0::13::INSTR", mock=True) == ""   # Advantest no *IDN?


def test_scan_and_identify_mock():
    found = scan_and_identify(mock=True)
    by_addr = {d.address: d for d in found}

    # Máy SCPI hiện đại -> tự khớp driver.
    assert by_addr["GPIB0::7::INSTR"].matched_key == "53131A"
    n1913 = by_addr["USB0::0x0957::0x1707::MY12345678::INSTR"]
    assert n1913.matched_key == "N1913A"
    # serial lấy từ trường thứ 3 của *IDN? (ở mock là serial cố định trong driver).
    assert n1913.serial == "MY00000002"

    # Máy đời cũ không *IDN? -> chưa khớp, cần wizard/gán tay.
    legacy = by_addr["GPIB0::13::INSTR"]
    assert legacy.matched_key is None
    assert legacy.is_matched is False
    assert legacy.display_model() == "(không trả lời *IDN?)"


# ---------------------------------------------------------------------------
# Wizard cắm-từng-máy (diff)
# ---------------------------------------------------------------------------

def test_diff_new_resources():
    before = {"GPIB0::3::INSTR", "GPIB0::7::INSTR"}
    after = before | {"GPIB0::13::INSTR"}
    assert diff_new_resources(before, after) == ["GPIB0::13::INSTR"]
    # Không có gì mới -> rỗng.
    assert diff_new_resources(after, after) == []


def test_snapshot_is_set():
    snap = snapshot_resources(mock=True)
    assert isinstance(snap, set) and snap


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

def test_check_connection_mock_ok():
    res = check_connection("53131A", "GPIB0::7::INSTR", mock=True)
    assert res.ok and "53131A" in res.model


def test_check_connection_unknown_model():
    res = check_connection("NOPE", "GPIB0::1::INSTR", mock=True)
    assert not res.ok and "registry" in res.error


# ---------------------------------------------------------------------------
# ConnectionProfile
# ---------------------------------------------------------------------------

def test_profile_address_map_and_roundtrip(tmp_path):
    prof = ConnectionProfile(name="Bàn cal 1")
    prof.set_entry(ProfileEntry("CNT91", "GPIB0::3::INSTR", label="Đếm A", serial="789012"))
    prof.set_entry(ProfileEntry("N1913A", "USB0::x::INSTR", label="Công suất"))
    assert prof.address_map() == {"CNT91": "GPIB0::3::INSTR", "N1913A": "USB0::x::INSTR"}

    # round-trip giữ nguyên nhãn thân thiện.
    path = tmp_path / "profile.json"
    prof.save_json(path)
    loaded = ConnectionProfile.load_json(path)
    assert loaded.address_map() == prof.address_map()
    by_model = {e.model_key: e for e in loaded.entries}
    assert by_model["CNT91"].label == "Đếm A"
    assert by_model["N1913A"].label == "Công suất"

    # ghi đè cùng model_key -> không tạo trùng.
    prof.set_entry(ProfileEntry("CNT91", "GPIB0::5::INSTR"))
    assert prof.address_map()["CNT91"] == "GPIB0::5::INSTR"
    assert len(prof.entries) == 2


def test_profile_warnings_duplicate_address():
    prof = ConnectionProfile()
    prof.set_entry(ProfileEntry("CNT91", "GPIB0::3::INSTR"))
    prof.set_entry(ProfileEntry("CNT90", "GPIB0::3::INSTR"))  # cùng địa chỉ
    assert any("bị gán cho cả" in w for w in prof.warnings())
