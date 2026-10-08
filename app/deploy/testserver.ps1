# Testserver auf diesem PC (Windows): startet eine FRISCHE Kopie der App im Testmodus.
# Der Testmodus sperrt jede Verbindung nach außen - es wird nichts geschaltet oder gesendet, die echte Anlage merkt nichts.
# Ideal zum Ausprobieren der Installation und zum Einspielen einer Sicherung.
#
#   .\testserver.ps1            neue, leere Testinstallation auf Port 8813 (bei erneutem Aufruf: alte Testdaten bleiben)
#   .\testserver.ps1 -Neu       Testdaten vorher löschen (wieder wie frisch installiert)
#   .\testserver.ps1 -Port 8820 anderer Port
#
# Beenden: Strg+C. Die Testdaten liegen in %TEMP%\BlueNexus-Test und stören die echte Installation nicht.
param([int]$Port = 8813, [switch]$Neu)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dest = Join-Path $env:TEMP "BlueNexus-Test"
if ($Neu -and (Test-Path $dest)) { Remove-Item $dest -Recurse -Force }
if (-not (Test-Path (Join-Path $dest "app\webapp.py"))) {
    New-Item -ItemType Directory -Force $dest | Out-Null
    Write-Host "Kopiere den Programmcode (ohne eure Daten) nach $dest ..."
    Push-Location $repo
    try {
        $zip = Join-Path $env:TEMP "BlueNexus-Test.zip"
        git archive --format=zip -o $zip HEAD app
        Expand-Archive $zip -DestinationPath $dest -Force; Remove-Item $zip
    } finally { Pop-Location }
    # nicht eingecheckte Änderungen mitnehmen (neue/geänderte Programmdateien)
    Push-Location $repo
    try {
        foreach ($f in (git ls-files -m -o --exclude-standard app)) {
            $t = Join-Path $dest $f; New-Item -ItemType Directory -Force (Split-Path $t) | Out-Null; Copy-Item $f $t -Force
        }
    } finally { Pop-Location }
}
$env:BLUENEXUS_SANDBOX = "1"; $env:PORT = "$Port"
Write-Host ""
Write-Host "  TESTMODUS - öffne im Browser:  http://localhost:$Port" -ForegroundColor Magenta
Write-Host "  Beenden mit Strg+C." -ForegroundColor Magenta
Write-Host ""
Set-Location (Join-Path $dest "app")
python webapp.py
