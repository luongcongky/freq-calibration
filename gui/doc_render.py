"""
gui/doc_render.py
==================
Chuyển .docx sang PDF rồi render từng trang PDF thành QPixmap — dùng để hiện
"bản xem nhanh" tài liệu ngay trong ứng dụng (khung bên phải Bước 3) mà
không cần mở Word/LibreOffice rời.

Convert theo thứ tự ưu tiên:
  1) Word COM (win32com) — nếu máy có cài Microsoft Word.
  2) LibreOffice headless (soffice --convert-to pdf) — dùng khi không có Word.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pymupdf as fitz  # "fitz" la ten cu, da doi thanh "pymupdf" tu ban 1.24 - import kieu nay tranh warning deprecated ma khong phai doi ten bien fitz.* ben duoi
from PyQt5.QtGui import QImage, QPixmap

_WD_EXPORT_FORMAT_PDF = 17  # wdExportFormatPDF

_SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _docx_to_pdf_word(docx_path: str, pdf_path: str) -> None:
    import win32com.client as win32  # import lazy: máy không có pywin32 vẫn dùng được nhánh LibreOffice

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(docx_path), ReadOnly=True)
        try:
            doc.ExportAsFixedFormat(OutputFileName=os.path.abspath(pdf_path),
                                     ExportFormat=_WD_EXPORT_FORMAT_PDF)
        finally:
            doc.Close(False)
    finally:
        word.Quit()


def _find_soffice() -> str:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for path in _SOFFICE_CANDIDATES:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "Không tìm thấy Microsoft Word hoặc LibreOffice trên máy này — "
        "cần cài 1 trong 2 để dùng tính năng xem nhanh tài liệu.")


def _docx_to_pdf_libreoffice(docx_path: str, pdf_path: str) -> None:
    soffice = _find_soffice()
    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    result = subprocess.run(
        [soffice, "--headless", "--norestore", "--convert-to", "pdf",
         "--outdir", out_dir, os.path.abspath(docx_path)],
        capture_output=True, text=True, timeout=60,
    )
    generated = os.path.join(
        out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.isfile(generated):
        raise RuntimeError(
            f"LibreOffice không tạo được PDF: {result.stderr or result.stdout}")
    if os.path.abspath(generated) != os.path.abspath(pdf_path):
        os.replace(generated, pdf_path)


def docx_to_pdf(docx_path: str, pdf_path: str) -> None:
    """Thử Word COM trước, lỗi (không có Word) thì tự chuyển sang LibreOffice."""
    try:
        _docx_to_pdf_word(docx_path, pdf_path)
        return
    except Exception:
        pass
    _docx_to_pdf_libreoffice(docx_path, pdf_path)


def render_pdf_pages(pdf_path: str, dpi: int = 150) -> list[QPixmap]:
    pixmaps: list[QPixmap] = []
    pdf = fitz.open(pdf_path)
    try:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page in pdf:
            pix = page.get_pixmap(matrix=matrix)
            fmt = QImage.Format_RGB888 if pix.n < 4 else QImage.Format_RGBA8888
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            pixmaps.append(QPixmap.fromImage(img.copy()))
    finally:
        pdf.close()
    return pixmaps


def docx_to_page_pixmaps(docx_path: str, dpi: int = 150) -> list[QPixmap]:
    """Convert 1 file .docx -> PDF tạm (cùng thư mục, cùng tên) -> list ảnh từng trang."""
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
    docx_to_pdf(docx_path, pdf_path)
    return render_pdf_pages(pdf_path, dpi=dpi)
