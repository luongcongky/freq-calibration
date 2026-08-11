"""
core/table_layouts.py
=======================
Tiêu đề cột CHÍNH XÁC của 11 bảng Biên Bản (TEMPLATE_FREQ 8 bảng,
TEMPLATE_POWER 3 bảng) — NGUỒN DUY NHẤT, dùng CHUNG bởi:
  - scripts/build_generic_seed_templates.py (dựng file .docx thật)
  - gui/report_preview.py (dựng bảng rà soát Bước 2/Bước 3)

Khách hàng yêu cầu bảng hiển thị trong app PHẢI GIỐNG HỆT bảng trong file
docx thật — tách tiêu đề cột ra đây để 2 nơi trên không thể lệch nhau theo
thời gian (trước đó mỗi nơi tự gõ tay 1 bản, dễ trôi dần).

Thuần dữ liệu (list[str]) hoặc hàm nhỏ tham số hoá theo n/kênh — không phụ
thuộc Qt/docx.
"""

from __future__ import annotations

FREQ_A1_HEADERS = ["Tần số thiết lập", "Tần số đo được\ntrên CNT-90XL\n(fCi)",
                   "Tần số đo được\ntrên CNT-90XL\n(fC)", "Sai số tần số\n(δf)",
                   "Sai số\ncho phép\n(δfcp)"]

FREQ_SENSITIVITY_HEADERS = ["Tần số thiết lập", "Độ nhạy đo được", "Độ nhạy cho phép"]

FREQ_A8_HEADERS = ["Tần số (chu kỳ) thiết lập trên Γ3-110, SMF-100A",
                   "Chu kỳ đo được (Tđo)", "Sai số đo\n(δT)", "Sai số cho phép\n(δTcp)"]


def freq_error_headers(channel: str) -> list:
    """A5/A6/A7 — channel: 'A'/'B'/'C'."""
    return ["Tần số thiết lập", f"Tần số đo được trên kênh {channel} (fđo)",
            "Sai số đo tần số\n(δf)", "Sai số\ncho phép"]


def power_a1_headers(group_size: int) -> list:
    """Bảng A1 QTHC 2.515:2021 (Phụ lục A) — 10 lần đo chia 2 NHÓM
    group_size cột (mẫu giấy dùng group_size=5: nhóm 1 = lần 1-5, nhóm 2 =
    lần 6-10, cùng dùng chung 1 bộ tiêu đề "lần 1".."lần {group_size}")."""
    return (["Công suất chuẩn\n(tại f = 50 MHz)"] +
            [f"lần {i}" for i in range(1, group_size + 1)] + ["Độ KĐBĐ"])


def power_a2_headers(n: int) -> list:
    return (["Tần số thiết lập\n(mức công suất 0 dBm)"] +
            [f"lần {i}" for i in range(1, n + 1)] + ["TB", "Độ KĐBĐ"])


def power_a3_headers(n: int) -> list:
    return (["Tần số thiết lập", "Công suất chuẩn\ntrên NRP2 (dBm)"] +
            [f"lần {i}" for i in range(1, n + 1)] + ["TB", "Độ KĐBĐ"])
