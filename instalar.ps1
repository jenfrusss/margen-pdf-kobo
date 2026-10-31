$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python. Instala Python 3.10 o posterior con el lanzador py.' }
}
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias Python.' }
New-Item -ItemType Directory -Force -Path tools | Out-Null
if (-not (Test-Path 'tools\kepubify.exe')) {
    Invoke-WebRequest 'https://github.com/pgaskin/kepubify/releases/download/v4.0.4/kepubify-windows-64bit.exe' -OutFile 'tools\kepubify.exe'
}
& '.venv\Scripts\python.exe' instalar_modelos.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar los modelos de traducción.' }

if (-not (Get-ChildItem 'tools\jre' -Filter java.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    $zip = Join-Path $PSScriptRoot 'tools\jre-download.zip'
    Invoke-WebRequest 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse' -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath 'tools\jre' -Force
    Remove-Item -LiteralPath $zip
}
if (-not (Get-ChildItem 'tools\epubcheck' -Filter epubcheck.jar -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    $zip = Join-Path $PSScriptRoot 'tools\epubcheck-download.zip'
    Invoke-WebRequest 'https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip' -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath 'tools\epubcheck' -Force
    Remove-Item -LiteralPath $zip
}
& '.venv\Scripts\python.exe' preparar_ocr.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el modelo OCR.' }
$stamp = (Get-FileHash 'requirements.txt').Hash + (Get-FileHash 'instalar.ps1').Hash
Set-Content -LiteralPath 'tools\install-stamp.txt' -Value $stamp -NoNewline
Write-Host 'Instalación lista. Ejecuta iniciar.ps1.'
