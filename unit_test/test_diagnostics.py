"""
unit_test/test_diagnostics.py
================================
Test core/diagnostics.py::export_diagnostic_bundle() — gom log + thông tin
hệ thống thành 1 file .zip để khách hàng gửi lại khi gặp sự cố (app chạy
offline tại máy khách, dev không truy cập từ xa được).
"""

import zipfile

import core.diagnostics as diagnostics


def test_export_diagnostic_bundle_includes_system_info(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path / "data_khong_ton_tai")

    out = tmp_path / "chan_doan.zip"
    diagnostics.export_diagnostic_bundle(out)

    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "system_info.txt" in names
        text = zf.read("system_info.txt").decode("utf-8")
        assert "Phiên bản app:" in text
        assert "RAM hiện tại" in text
        assert "Hệ điều hành:" in text


def test_export_diagnostic_bundle_includes_rotated_log_files(tmp_path, monkeypatch):
    log_dir = tmp_path / "data"
    log_dir.mkdir()
    (log_dir / "app.log").write_text("dong log 1\n", encoding="utf-8")
    (log_dir / "app.log.1").write_text("dong log cu\n", encoding="utf-8")
    (log_dir / "khac.txt").write_text("khong lien quan\n", encoding="utf-8")
    monkeypatch.setattr(diagnostics, "LOG_DIR", log_dir)

    out = tmp_path / "chan_doan.zip"
    diagnostics.export_diagnostic_bundle(out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "app.log" in names
        assert "app.log.1" in names
        assert "khac.txt" not in names   # chỉ gom file app.log*, không gom file khác trong data/
