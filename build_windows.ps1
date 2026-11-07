# Builds dist\mousephone-<version>-windows-setup.exe. The Windows
# counterpart of build.sh; run it on Windows, from the repo folder:
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Releases are built by GitHub Actions (.github/workflows/windows.yml),
# so you only need this to build locally.
#
# Signing: like build.sh, builds are signed with the same certificate every
# time, and the in-app updater only installs updates signed with it. Set
# MOUSEPHONE_SIGNING_PFX (path to the .pfx from
# tools/create_windows_signing_cert.sh) and MOUSEPHONE_SIGNING_PASSWORD.
# For a quick local test build without the certificate, pass -Unsigned
# (that copy then can't verify, so won't install, updates).
#
# Needs: Python 3.11+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Signing also needs signtool.exe, from the Windows SDK.

param([switch]$Unsigned)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Native commands don't trip $ErrorActionPreference, so check each one.
# Deliberately a plain (non-advanced) function: flags like -m then pass
# through in $args instead of being parsed as this function's parameters.
function Invoke-Checked {
  $exe, $rest = $args
  & $exe @rest
  if ($LASTEXITCODE -ne 0) { throw "$exe exited with code $LASTEXITCODE" }
}

function Find-Tool {
  param([string]$Name, [string[]]$Candidates, [string]$Hint)
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($pattern in $Candidates) {
    $found = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($found) { return $found[0].FullName }
  }
  throw "$Name not found. $Hint"
}

$version = (Select-String -Path mouse_server.py -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value
if (-not $version) { throw "Couldn't read __version__ from mouse_server.py." }

if (-not $Unsigned) {
  if (-not $env:MOUSEPHONE_SIGNING_PFX -or -not (Test-Path $env:MOUSEPHONE_SIGNING_PFX)) {
    throw "Set MOUSEPHONE_SIGNING_PFX to the signing .pfx (or pass -Unsigned for a local test build)."
  }
  $signtool = Find-Tool "signtool.exe" @("${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe") `
    "Install the Windows SDK, or pass -Unsigned."
}
$iscc = Find-Tool "iscc.exe" @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) "Install it with: winget install JRSoftware.InnoSetup"

function Sign([string]$Path) {
  if ($Unsigned) { return }
  Invoke-Checked $signtool sign /f $env:MOUSEPHONE_SIGNING_PFX /p $env:MOUSEPHONE_SIGNING_PASSWORD /fd SHA256 $Path
}

Write-Host "Building mousephone $version for Windows..."

Write-Host "Setting up a temporary build environment..."
Invoke-Checked python -m venv build_env_win
$py = ".\build_env_win\Scripts\python.exe"
Invoke-Checked $py -m pip install --upgrade pip --quiet
Invoke-Checked $py -m pip install aiohttp "qrcode[pil]" pystray certifi pyinstaller --quiet

Write-Host "Building the app..."
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
# --windowed: a tray app, no console window. The Mac backend is only
# imported on macOS; keep it out of the Windows build.
Invoke-Checked $py -m PyInstaller --noconfirm --windowed --name mousephone `
  --icon assets\mousephone.ico `
  --add-data "assets\mousephone.ico;assets" `
  --hidden-import platforms.windows `
  --exclude-module platforms.mac `
  mouse_server.py

Sign "dist\mousephone\mousephone.exe"

Write-Host "Building the installer..."
Invoke-Checked $iscc /Q "/DAppVersion=$version" installer\mousephone.iss
$setup = "dist\mousephone-$version-windows-setup.exe"
Sign $setup

Write-Host ""
Write-Host "=================================================="
Write-Host "Done! Installer: $setup"
if ($Unsigned) { Write-Host "(unsigned test build: it won't be able to install updates)" }
Write-Host "=================================================="
