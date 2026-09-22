# Assemble the portable desktop build, dist\DepthWizard\ = Tauri shell + PyInstaller backend.
# Run after both builds (desktop\README.md). Only the generated dist\DepthWizard\ is replaced.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$shell = Join-Path $root 'desktop\src-tauri\target\release\depthwizard.exe'
$backend = Join-Path $root 'dist\depthwizard-backend'
$out = Join-Path $root 'dist\DepthWizard'
foreach ($path in @($shell, $backend)) {
    if (-not (Test-Path $path)) { throw "Missing $path. Build it first (see desktop\README.md)." }
}
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item $shell $out
Copy-Item -Recurse $backend (Join-Path $out 'backend')
$sizeGb = (Get-ChildItem -Recurse $out | Measure-Object -Sum Length).Sum / 1GB
Write-Output ("Portable app: {0} ({1:N1} GB). Run depthwizard.exe inside it." -f $out, $sizeGb)
