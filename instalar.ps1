$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) { py -m venv .venv }
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
New-Item -ItemType Directory -Force -Path tools | Out-Null
if (-not (Test-Path 'tools\kepubify.exe')) {
    Invoke-WebRequest 'https://github.com/pgaskin/kepubify/releases/download/v4.0.4/kepubify-windows-64bit.exe' -OutFile 'tools\kepubify.exe'
}
Write-Host 'Instalación lista. Ejecuta iniciar.ps1.'
