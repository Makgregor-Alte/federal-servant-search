# Compilação do cliente desktop para Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Python 3 indisponivel para criar o ambiente." }
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar PyInstaller." }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name FederalServantSearch main.py
if ($LASTEXITCODE -ne 0) { throw "Falha na compilacao do executavel." }
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "release") | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "dist\FederalServantSearch.exe") -Destination (Join-Path $PSScriptRoot "release\FederalServantSearch.exe") -Force
Write-Host "Executavel para entrega: $PSScriptRoot\release\FederalServantSearch.exe"
