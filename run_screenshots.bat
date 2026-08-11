@echo off
cd /d "%~dp0"
echo ============================================
echo  Dang chup anh man hinh freq_calibration...
echo ============================================

if exist ".venv\Scripts\python.exe" (
    echo Using .venv Python...
    ".venv\Scripts\python.exe" take_screenshots.py
) else (
    echo Using system Python...
    python take_screenshots.py
)

echo.
if %ERRORLEVEL% == 0 (
    echo XONG! Mo thu muc screenshots...
    explorer screenshots
) else (
    echo CO LOI! Kiem tra lai.
    pause
)
