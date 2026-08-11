"""
core/report_templates/base.py
==============================
Lớp trừu tượng BaseReportTemplate — định nghĩa giao diện mà mỗi template
kiểm định phải triển khai.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.session import CalibrationSession, SessionTest, ReportTable
from core.paths import SCENARIOS_DIR


class BaseReportTemplate(ABC):
    TEMPLATE_ID: str = ""
    TEMPLATE_NAME: str = ""          # Hiển thị trong UI
    DUT_MODELS: list[str] = []       # Các model thiết bị áp dụng
    STANDARD: str = ""               # "QTKĐ 2.461 : 2018"
    MEASUREMENT_RANGE: str = ""      # "0,002 Hz đến 27 GHz"

    GCN_STYLE: str = "same_as_bienban"
    """Cách GCN thể hiện dữ liệu bảng — dùng bởi gui/template_manager_dialog.py
    để quyết định có hiện form "gcn.param_name/limit_str" khi thêm 1 bảng
    vào template ĐÃ CÓ hay không (quản trị viên tự gõ tag trong Word, app
    không chèn gì cả — field này chỉ ảnh hưởng UI form, không phải ghi file):
      "same_as_bienban" — mỗi bảng dùng `tables.<ID>.result`/`.report_val()`
        ngay trong gcnkd.docx (như NRP2, và MỌI template mới đăng ký) —
        không cần form gcn riêng.
      "summary_rows" — bảng tổng hợp 1 dòng/bài, vòng lặp Jinja động đọc
        thẳng `descriptor.gcn` (chỉ CNT90XL, cơ chế cũ giữ nguyên) — gcnkd.docx
        không dùng cơ chế "tables.X" nên KHÔNG được gõ `tables.<ID>.*` vào
        đó, chỉ cần điền form gcn.param_name/limit_str."""

    @abstractmethod
    def default_tests(self) -> list[SessionTest]:
        """
        Trả về danh sách SessionTest mặc định (với scenario_path trỏ tới
        thư mục scenarios/<subdir>/). Được gọi khi tạo phiên mới.
        """

    @abstractmethod
    def map_test_result(self, test: SessionTest) -> ReportTable:
        """
        Chuyển step_results của bài test thành ReportTable có cấu trúc.
        Được gọi sau khi scenario chạy xong.
        """

    def fill_session_defaults(self, session: CalibrationSession) -> None:
        """Điền các giá trị mặc định từ template vào meta của session."""
        session.meta.dut.model = self.DUT_MODELS[0] if self.DUT_MODELS else ""
        session.meta.dut.measurement_range = self.MEASUREMENT_RANGE

    def generate_bienban(self, session: CalibrationSession, output_path) -> Path:
        """Sinh Biên Bản Kiểm Định/Hiệu Chuẩn — mặc định dùng mẫu QTKĐ 2.461
        (CNT-90XL). Template khác override để dùng mẫu xuất riêng của mình."""
        from core.report_generator import generate_bienban as _gen
        return _gen(session, output_path)

    def generate_gcnkd(self, session: CalibrationSession, output_path) -> Path:
        """Sinh Giấy Chứng Nhận Kiểm Định/Hiệu Chuẩn — mặc định dùng mẫu
        QTKĐ 2.461 (CNT-90XL). Template khác override để dùng mẫu riêng."""
        from core.report_generator import generate_gcnkd as _gen
        return _gen(session, output_path)

    @property
    def scenarios_dir(self) -> Path:
        """Thư mục chứa các file scenario .json của template này."""
        return SCENARIOS_DIR / self.TEMPLATE_ID.lower().replace("_", "/", 1).split("/")[-1]

    @property
    def tables_dir(self) -> Path:
        """Thư mục chứa descriptor JSON từng bảng — dùng bởi
        gui/template_manager_dialog.py khi thêm 1 bảng mới vào template ĐÃ CÓ
        (không cần biết template này viết tay hay data-driven)."""
        raise NotImplementedError

    @property
    def bienban_docx_path(self) -> Path:
        """Đường dẫn file .docx mẫu Biên Bản SỐNG của template này."""
        raise NotImplementedError

    @property
    def gcnkd_docx_path(self) -> Path:
        """Đường dẫn file .docx mẫu GCN SỐNG của template này."""
        raise NotImplementedError
