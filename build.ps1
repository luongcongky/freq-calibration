<#
.SYNOPSIS
    Build phần mềm freq-calibration thành thư mục portable (có freq-calibration.exe).

.DESCRIPTION
    Tự tạo venv, cài thư viện + PyInstaller, build kiểu one-dir (portable),
    copy scenario mẫu cạnh exe, rồi (tuỳ chọn) nén .zip để giao khách.

    LƯU Ý: NI-VISA KHÔNG được đóng gói. Máy khách phải tự cài NI-VISA nếu nối
    thiết bị GPIB thật. Bản .exe vẫn chạy giao diện + chế độ mock mà không cần NI-VISA.

.PARAMETER Console
    Build kèm cửa sổ console để xem log (dùng khi debug). Mặc định là --windowed.

.PARAMETER Zip
    Nén kết quả thành freq-calibration-portable.zip để giao khách.

.EXAMPLE
    .\build.ps1            # build bản giao khách (windowed)
    .\build.ps1 -Console   # build bản debug (thấy log)
    .\build.ps1 -Zip       # build + nén .zip
#>
param(
    [switch]$Console,
    [switch]$Zip
)

# Native tool (pip/pyinstaller) ghi log ra stderr; de "Continue" de stderr KHONG
# bi hieu nham la loi. Thay vao do kiem tra $LASTEXITCODE that su sau moi lenh.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Assert-LastExit($what) {
    if ($LASTEXITCODE -ne 0) { Write-Error "$what that bai (exit $LASTEXITCODE)"; exit 1 }
}

$AppName = "freq-calibration"
$DistDir = Join-Path $PSScriptRoot "dist\$AppName"

Write-Host "==> [1/4] Chuan bi moi truong ao + thu vien" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv; Assert-LastExit "Tao venv" }
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip;        Assert-LastExit "Nang cap pip"
pip install -r requirements.txt;            Assert-LastExit "Cai requirements"
pip install pyinstaller;                    Assert-LastExit "Cai pyinstaller"

Write-Host "==> [2/4] Build PyInstaller (one-dir)" -ForegroundColor Cyan
$windowFlag = if ($Console) { "--console" } else { "--windowed" }
pyinstaller --noconfirm --clean $windowFlag --name $AppName `
    --hidden-import pyvisa_py `
    main.py
Assert-LastExit "PyInstaller build"

Write-Host "==> [3/4] Copy scenario mau canh exe" -ForegroundColor Cyan
if (Test-Path "scenarios") {
    Copy-Item -Recurse -Force "scenarios" (Join-Path $DistDir "scenarios")
}

Write-Host "==> [4/4] Hoan tat" -ForegroundColor Cyan
Write-Host "Thu muc portable: $DistDir" -ForegroundColor Green
Write-Host "Chay thu: $DistDir\$AppName.exe" -ForegroundColor Green

if ($Zip) {
    $zipPath = Join-Path $PSScriptRoot "$AppName-portable.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path "$DistDir\*" -DestinationPath $zipPath
    Write-Host "Da nen: $zipPath  (gui file nay cho khach)" -ForegroundColor Green
}
