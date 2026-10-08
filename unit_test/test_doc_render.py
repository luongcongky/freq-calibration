"""
unit_test/test_doc_render.py
===============================
Test gui/doc_render.py::render_pdf_pages() — REG-RAM-02
(test_reports/2026-10-01_regression2/BAO_CAO_TEST_LAI_2.md): "Xem nhanh"
15 lần tăng ~5 MB/lần (Private Bytes), không giảm dù chờ/đổi bước/mở-đóng
cửa sổ khác, và không thấy khi dùng EmptyWorkingSet.

Đo thực nghiệm xác nhận nguyên nhân: PyMuPDF giữ 1 "store" (cache ảnh/font
đã render) ở tầng C, KHÔNG phải object Python nên gc.collect() không thấy/
không dọn được — mỗi lần render_pdf_pages() phình cache thêm, không bao giờ
co lại. fitz.TOOLS.store_shrink(100) sau khi render xong xả cache này —
chạy lặp lại trên CÙNG 1 file PDF 6 lần không tăng RAM nữa (đã đo: tăng dần
~5 MB/lần -> phẳng hoàn toàn khi gọi store_shrink sau mỗi lần)."""

from pathlib import Path

import pymupdf as fitz
import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication

from gui.doc_render import render_pdf_pages

_app = QApplication.instance() or QApplication([])


def _make_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "hello")
    doc.save(str(path))
    doc.close()


def test_render_pdf_pages_returns_one_pixmap_per_page(tmp_path):
    pdf_path = tmp_path / "a.pdf"
    _make_pdf(pdf_path)
    pixmaps = render_pdf_pages(str(pdf_path))
    assert len(pixmaps) == 1
    assert pixmaps[0].width() > 0 and pixmaps[0].height() > 0


def test_render_pdf_pages_shrinks_mupdf_store_after_rendering(tmp_path, monkeypatch):
    """Xác nhận store_shrink(100) được gọi SAU KHI render xong (dù thành
    công hay lỗi) — đây là chỗ sửa thật cho REG-RAM-02, không phải chỉ đo
    RAM gián tiếp (chậm/không ổn định trong CI)."""
    pdf_path = tmp_path / "a.pdf"
    _make_pdf(pdf_path)

    calls = []
    monkeypatch.setattr(fitz.TOOLS, "store_shrink", lambda pct: calls.append(pct))

    render_pdf_pages(str(pdf_path))

    assert calls == [100]


def test_render_pdf_pages_shrinks_store_even_if_rendering_fails(tmp_path, monkeypatch):
    pdf_path = tmp_path / "a.pdf"
    _make_pdf(pdf_path)

    calls = []
    monkeypatch.setattr(fitz.TOOLS, "store_shrink", lambda pct: calls.append(pct))

    import gui.doc_render as doc_render_mod

    real_matrix = fitz.Matrix

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(fitz, "Matrix", _boom)
    try:
        with pytest.raises(RuntimeError):
            render_pdf_pages(str(pdf_path))
    finally:
        monkeypatch.setattr(fitz, "Matrix", real_matrix)

    assert calls == [100]


def test_repeated_rendering_of_same_pdf_calls_store_shrink_every_time(tmp_path, monkeypatch):
    """store_shrink phải chạy ở MỖI lần render (không chỉ lần đầu) — nếu
    không, cache vẫn phình dần qua nhiều lần "Xem nhanh" liên tiếp."""
    pdf_path = tmp_path / "a.pdf"
    _make_pdf(pdf_path)

    calls = []
    monkeypatch.setattr(fitz.TOOLS, "store_shrink", lambda pct: calls.append(pct))

    for _ in range(5):
        render_pdf_pages(str(pdf_path))

    assert calls == [100] * 5
