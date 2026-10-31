$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { & '.\instalar.ps1' }
Start-Process 'http://127.0.0.1:8765'
& '.venv\Scripts\python.exe' app.py
