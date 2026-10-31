$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$stamp = (Get-FileHash 'requirements.txt').Hash + (Get-FileHash 'instalar.ps1').Hash
$installed = if (Test-Path 'tools\install-stamp.txt') { (Get-Content 'tools\install-stamp.txt' -Raw).Trim() } else { '' }
if (-not (Test-Path '.venv\Scripts\python.exe') -or $installed -ne $stamp) { & '.\instalar.ps1' }
Start-Process 'http://127.0.0.1:8765'
& '.venv\Scripts\python.exe' app.py
