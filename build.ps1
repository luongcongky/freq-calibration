<#
.SYNOPSIS
    Build phan mem freq-calibration va lap rap thu muc giao khach (release/).

.DESCRIPTION
    Danh cho NGUOI DONG GOI (dev), khong phai khach hang.

    Quy trinh:
      1. Tao venv, cai thu vien + PyInstaller.
      2. Build PyInstaller kieu one-dir vao dist\freq-calibration
         (thu muc trung gian, KHONG giao cho khach).
      3. Lap rap thu muc release\freq-calibration-vX.Y.Z\ = ban HOAN CHINH
         de giao khach: exe + scenarios + templates + tai lieu huong dan +
         BUILD_INFO.txt (ghi phien ban + commit de doi chieu khi khach
         bao loi).
      4. (Tuy chon -Zip) Nen thu muc release do thanh .zip - DAY LA FILE
         GUI CHO KHACH, khong gui thu muc dist/.

    LUU Y: NI-VISA KHONG duoc dong goi. May khach phai tu cai NI-VISA neu
    noi thiet bi GPIB that. Ban .exe van chay giao dien + che do mock ma
    khong can NI-VISA.

.PARAMETER Console
    Build kem cua so console de xem log (dung khi debug). Mac dinh la --windowed.

.PARAMETER Zip
    Nen ket qua trong release\ thanh file .zip de giao khach.

.EXAMPLE
    .\build.ps1            # build + lap rap thu muc release\ (windowed)
    .\build.ps1 -Console   # build ban debug (thay log)
    .\build.ps1 -Zip       # build + lap rap + nen .zip san sang gui khach
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

Write-Host "==> [1/5] Chuan bi moi truong ao + thu vien" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv; Assert-LastExit "Tao venv" }
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip;        Assert-LastExit "Nang cap pip"
pip install -r requirements.txt;            Assert-LastExit "Cai requirements"
pip install pyinstaller;                    Assert-LastExit "Cai pyinstaller"

Write-Host "==> [2/5] Build PyInstaller (one-dir, ban trung gian trong dist\)" -ForegroundColor Cyan
$windowFlag = if ($Console) { "--console" } else { "--windowed" }
# --splash: hien anh ngay tu bootloader (truoc khi Python/Qt kip nap), giup
# nguoi dung thay phan hoi tuc thi ngay ca khi lan dau chay bi Windows
# Defender quet cham (van la nguyen nhan chinh, splash chi giam cam giac
# "treo" chu khong lam qua trinh quet nhanh hon).
pyinstaller --noconfirm --clean $windowFlag --name $AppName `
    --hidden-import pyvisa_py `
    --splash "packaging\splash.png" `
    main.py
Assert-LastExit "PyInstaller build"

Write-Host "==> [3/5] Lap rap thu muc giao khach (release\)" -ForegroundColor Cyan
$Version = (Get-Content "VERSION" -Raw).Trim()
$GitHash = (git rev-parse --short HEAD 2>$null)
if (-not $GitHash) { $GitHash = "unknown" }
$ReleaseName = "$AppName-v$Version"
$ReleaseDir = Join-Path $PSScriptRoot "release\$ReleaseName"

if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Copy-Item -Recurse -Force "$DistDir\*" $ReleaseDir
if (Test-Path "scenarios") { Copy-Item -Recurse -Force "scenarios" (Join-Path $ReleaseDir "scenarios") }
if (Test-Path "templates") { Copy-Item -Recurse -Force "templates" (Join-Path $ReleaseDir "templates") }
# gui/logo.png, gui/logo.ico: PyInstaller chi dong goi module .py, khong tu
# nhan ra day la tai nguyen can cho lenh QIcon("gui/logo.png") (duong dan
# tuong doi tinh trong code) -> phai copy tay giong scenarios/templates.
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "gui") | Out-Null
Copy-Item -Force "gui\logo.png" (Join-Path $ReleaseDir "gui\logo.png")
Copy-Item -Force "gui\logo.ico" (Join-Path $ReleaseDir "gui\logo.ico")
if (Test-Path "Huong_dan_su_dung_freq_calibration.docx") {
    Copy-Item -Force "Huong_dan_su_dung_freq_calibration.docx" $ReleaseDir
}
Copy-Item -Force "packaging\CUSTOMER_README.txt" (Join-Path $ReleaseDir "0_DOC_TRUOC_KHI_CHAY.txt")

$buildInfo = @"
freq-calibration - thong tin ban build
Phien ban : $Version
Commit    : $GitHash
Ngay build: $(Get-Date -Format "yyyy-MM-dd HH:mm")
"@
[System.IO.File]::WriteAllText((Join-Path $ReleaseDir "BUILD_INFO.txt"), $buildInfo, [System.Text.Encoding]::UTF8)

Write-Host "==> [4/5] Hoan tat lap rap" -ForegroundColor Cyan
Write-Host "Thu muc giao khach: $ReleaseDir" -ForegroundColor Green
Write-Host "Chay thu: $ReleaseDir\$AppName.exe" -ForegroundColor Green

Write-Host "==> [5/5] Nen file .zip (neu co -Zip)" -ForegroundColor Cyan
if ($Zip) {
    $zipPath = Join-Path $PSScriptRoot "release\$ReleaseName.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path "$ReleaseDir\*" -DestinationPath $zipPath
    Write-Host "Da nen: $zipPath  <-- GUI FILE NAY CHO KHACH" -ForegroundColor Green
} else {
    Write-Host "(Bo qua nen zip - chay lai voi -Zip de tao file .zip gui khach)" -ForegroundColor DarkYellow
}
