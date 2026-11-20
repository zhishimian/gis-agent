<#
.SYNOPSIS
    Build OpenGIS Studio desktop artifacts (portable zip + NSIS one-click setup.exe).
#>
param(
    [switch]$SkipFrontend,
    [switch]$SkipRuntime,
    [switch]$PortableOnly,
    [switch]$UseChinaMirror
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$DistDir = Join-Path $RepoRoot "dist"
$StagingRuntime = Join-Path $DistDir "staging\runtime"
$ResourcesRuntime = Join-Path $RepoRoot "desktop\src-tauri\resources\runtime"
$PortableDir = Join-Path $DistDir "OpenGIS-Studio-9.1.0-x64-portable"

function Clear-StaleProxy {
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:ALL_PROXY = ""
    $env:PROJ_LIB = ""
    $env:PROJ_DATA = ""
    $env:GDAL_DATA = ""
}

Clear-StaleProxy

if (-not $SkipFrontend) {
    Write-Host "==> [1/5] Building frontend and syncing static SPA..." -ForegroundColor Cyan
    pnpm --dir frontend run build:sync
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}

if (-not $SkipRuntime) {
    Write-Host "==> [2/5] Assembling isolated portable Python 3.12 spatial runtime..." -ForegroundColor Cyan
    $uvPyDir = (& uv python dir).Trim()
    $BasePythonDir = $null
    if ($uvPyDir -and (Test-Path $uvPyDir)) {
        $cand = Get-ChildItem -Path $uvPyDir -Directory -Filter "cpython-3.12*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Where-Object { Test-Path (Join-Path $_.FullName "python.exe") } |
            Select-Object -First 1
        if ($cand) { $BasePythonDir = $cand.FullName }
    }
    if (-not $BasePythonDir) {
        Push-Location $env:TEMP
        try {
            $pyExe = (& uv python find --no-project --python-preference only-managed 3.12).Trim()
            if ($pyExe -and (Test-Path $pyExe)) { $BasePythonDir = Split-Path -Parent $pyExe }
        } finally {
            Pop-Location
        }
    }
    if (-not $BasePythonDir -or -not (Test-Path (Join-Path $BasePythonDir "python.exe"))) {
        throw "Could not find standalone uv-managed Python 3.12. Run 'uv python install 3.12' first."
    }

    if (Test-Path $StagingRuntime) { Remove-Item $StagingRuntime -Recurse -Force }
    New-Item -ItemType Directory -Path (Split-Path -Parent $StagingRuntime) -Force | Out-Null
    Copy-Item -Path $BasePythonDir -Destination $StagingRuntime -Recurse -Force

    $TargetPy = Join-Path $StagingRuntime "python.exe"
    Clear-StaleProxy
    uv pip install --system --python $TargetPy --break-system-packages ".[cli,geo,studio]"
    if ($LASTEXITCODE -ne 0) { throw "uv pip install into portable runtime failed." }

    # Hatchling excludes gitignored static/* when building wheel; copy built frontend explicitly.
    $PkgStaticDir = Join-Path $StagingRuntime "Lib\site-packages\gis_agent\server\static"
    New-Item -ItemType Directory -Path $PkgStaticDir -Force | Out-Null
    Copy-Item -Path (Join-Path $RepoRoot "frontend\dist\*") -Destination $PkgStaticDir -Recurse -Force

    Write-Host "==> [3/5] Trimming redundant test/doc caches in portable runtime..." -ForegroundColor Cyan
    $RemoveRelative = @("Lib\test", "tcl", "Lib\tkinter", "Lib\idlelib", "Lib\ensurepip")
    foreach ($rel in $RemoveRelative) {
        $full = Join-Path $StagingRuntime $rel
        if (Test-Path $full) { Remove-Item $full -Recurse -Force }
    }
    Get-ChildItem -Path (Join-Path $StagingRuntime "Lib\site-packages") -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("tests", "test", "docs", "examples") } |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    Get-ChildItem -Path $StagingRuntime -Recurse -Include "__pycache__" -Directory -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $StagingRuntime -Recurse -Include "*.pdb","*.pyc","*.pyo" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    # Clean-PATH isolated import self-check (force no user-site pollution)
    $CheckCode = "import sys, fastapi, uvicorn, geopandas, pyogrio, rasterio, shapely, scipy, matplotlib, cartopy, gis_agent.server.app; assert sys.prefix.lower() in geopandas.__file__.lower(), geopandas.__file__; print('PORTABLE_RUNTIME_IMPORTS_OK:', geopandas.__file__)"
    $cleanCmd = "set PYTHONPATH=& set VIRTUAL_ENV=& set PYTHONNOUSERSITE=1& set PROJ_LIB=& set PROJ_DATA=& set GDAL_DATA=& set PATH=C:\Windows\System32;C:\Windows& `"$TargetPy`" -s -c `"$CheckCode`""
    cmd /c $cleanCmd
    if ($LASTEXITCODE -ne 0) { throw "Clean-PATH portable runtime import check failed." }
}

Write-Host "==> [4/5] Building Tauri v2 desktop binary & installers..." -ForegroundColor Cyan
$TmpCargo = Join-Path $env:TEMP ("opengis-cargo-" + [guid]::NewGuid().ToString("N") + ".toml")
if ($UseChinaMirror) {
@"
[http]
proxy = ""

[source.crates-io]
replace-with = "rsproxy-sparse"

[source.rsproxy-sparse]
registry = "sparse+https://rsproxy.cn/index/"
"@ | Set-Content -Path $TmpCargo -Encoding UTF8
} else {
@"
[http]
proxy = ""
"@ | Set-Content -Path $TmpCargo -Encoding UTF8
}

if (Test-Path $ResourcesRuntime) { Remove-Item $ResourcesRuntime -Recurse -Force }
New-Item -ItemType Directory -Path (Split-Path -Parent $ResourcesRuntime) -Force | Out-Null
Copy-Item -Path $StagingRuntime -Destination $ResourcesRuntime -Recurse -Force

pnpm --dir desktop install
if ($LASTEXITCODE -ne 0) { throw "pnpm desktop install failed." }

Push-Location (Join-Path $RepoRoot "desktop")
try {
    $TauriBin = ".\node_modules\.bin\tauri.cmd"
    if ($PortableOnly) {
        & $TauriBin build --no-bundle -- --config $TmpCargo --offline
        if ($LASTEXITCODE -ne 0) { throw "Tauri --no-bundle build failed." }
    } else {
        & $TauriBin build --bundles nsis --config src-tauri/tauri.release.conf.json -- --config $TmpCargo --offline
        if ($LASTEXITCODE -ne 0) { throw "Tauri NSIS build failed." }
    }
} finally {
    Pop-Location
    Remove-Item $TmpCargo -ErrorAction SilentlyContinue
}

Write-Host "==> [5/5] Staging portable zip and NSIS installer under dist/..." -ForegroundColor Cyan
$ExeSrc = Join-Path $RepoRoot "desktop\src-tauri\target\release\opengis-studio.exe"
if (-not (Test-Path $ExeSrc)) { throw "Missing release exe at $ExeSrc" }

if (Test-Path $PortableDir) { Remove-Item $PortableDir -Recurse -Force }
New-Item -ItemType Directory -Path $PortableDir -Force | Out-Null
Copy-Item -Path $ExeSrc -Destination (Join-Path $PortableDir "OpenGIS-Studio.exe") -Force
Copy-Item -Path $StagingRuntime -Destination (Join-Path $PortableDir "runtime") -Recurse -Force
@"
OpenGIS Studio v9.1.0 (Portable)
================================
1. Double-click OpenGIS-Studio.exe to launch (zero Python/QGIS/Git prerequisites).
2. On first run, open Settings -> enter your DeepSeek / OpenAI API Key (stored in Windows Credential Manager).
3. Drag .shp / .gpkg / .geojson / .tif files directly onto the map canvas or switch working folders via the top bar.
"@ | Set-Content -Path (Join-Path $PortableDir "README_FIRST.txt") -Encoding UTF8

$PortableZip = Join-Path $DistDir "OpenGIS-Studio-9.1.0-x64-portable.zip"
if (Test-Path $PortableZip) { Remove-Item $PortableZip -Force }
Compress-Archive -Path $PortableDir -DestinationPath $PortableZip -CompressionLevel Optimal

if (-not $PortableOnly) {
    $NsisDir = Join-Path $RepoRoot "desktop\src-tauri\target\release\bundle\nsis"
    $SetupSrc = Get-ChildItem -Path $NsisDir -Filter "*setup.exe" | Select-Object -First 1
    if ($SetupSrc) {
        $SetupDest = Join-Path $DistDir "OpenGIS-Studio-9.1.0-x64-setup.exe"
        Copy-Item -Path $SetupSrc.FullName -Destination $SetupDest -Force
        Write-Host "NSIS Setup : $SetupDest ($([math]::Round((Get-Item $SetupDest).Length / 1MB, 1)) MB)" -ForegroundColor Green
    }
}
Write-Host "Portable Zip: $PortableZip ($([math]::Round((Get-Item $PortableZip).Length / 1MB, 1)) MB)" -ForegroundColor Green
