"""
gui/doc_render.py
==================
Chuyển .docx/.xlsx sang PDF rồi render từng trang PDF thành QPixmap — dùng để
hiện "bản xem nhanh" tài liệu ngay trong ứng dụng (khung bên phải Bước 3) mà
không cần mở Word/Excel/LibreOffice rời.

Convert theo thứ tự ưu tiên:
  1) COM (win32com) — Word.Application cho .docx, Excel.Application cho
     .xlsx — nếu máy có cài Microsoft Office tương ứng.
  2) LibreOffice headless (soffice --convert-to pdf) — dùng khi không có
     Office (hàm này KHÔNG quan tâm đuôi file, dùng chung cho cả 2 định dạng).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PyQt5.QtGui import QImage, QPixmap

_WD_EXPORT_FORMAT_PDF = 17  # wdExportFormatPDF
_XL_TYPE_PDF = 0  # xlTypePDF (XlFixedFormatType)

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


def _xlsx_to_pdf_excel(xlsx_path: str, pdf_path: str) -> None:
    import win32com.client as win32  # import lazy: máy không có pywin32 vẫn dùng được nhánh LibreOffice

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(os.path.abspath(xlsx_path), ReadOnly=True)
        try:
            wb.ExportAsFixedFormat(Type=_XL_TYPE_PDF, Filename=os.path.abspath(pdf_path))
        finally:
            wb.Close(False)
    finally:
        excel.Quit()


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


def _convert_to_pdf_libreoffice(src_path: str, pdf_path: str) -> None:
    """Không quan tâm đuôi file (.docx/.xlsx/...) — dùng chung cho mọi định
    dạng LibreOffice mở được."""
    soffice = _find_soffice()
    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    result = subprocess.run(
        [soffice, "--headless", "--norestore", "--convert-to", "pdf",
         "--outdir", out_dir, os.path.abspath(src_path)],
        capture_output=True, text=True, timeout=60,
    )
    generated = os.path.join(
        out_dir, os.path.splitext(os.path.basename(src_path))[0] + ".pdf")
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
    _convert_to_pdf_libreoffice(docx_path, pdf_path)


def xlsx_to_pdf(xlsx_path: str, pdf_path: str) -> None:
    """Thử Excel COM trước, lỗi (không có Excel) thì tự chuyển sang LibreOffice."""
    try:
        _xlsx_to_pdf_excel(xlsx_path, pdf_path)
        return
    except Exception:
        pass
    _convert_to_pdf_libreoffice(xlsx_path, pdf_path)


def render_pdf_pages(pdf_path: str, dpi: int = 150) -> list[QPixmap]:
    # import lazy: pymupdf keo theo DLL MuPDF khá nặng — chỉ nạp khi thực sự
    # xem nhanh tài liệu (Bước 3), không phải ngay lúc khởi động app (module
    # này bị session_manager.py import từ đầu, nếu để "import pymupdf" ở
    # top-level sẽ nạp DLL đó ngay cả khi user chưa bao giờ bấm "Xem nhanh").
    import pymupdf as fitz  # "fitz" la ten cu, da doi thanh "pymupdf" tu ban 1.24
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


def xlsx_to_page_pixmaps(xlsx_path: str, dpi: int = 150) -> list[QPixmap]:
    """Convert 1 file .xlsx -> PDF tạm (cùng thư mục, cùng tên) -> list ảnh từng trang."""
    pdf_path = os.path.splitext(xlsx_path)[0] + ".pdf"
    xlsx_to_pdf(xlsx_path, pdf_path)
    return render_pdf_pages(pdf_path, dpi=dpi)
