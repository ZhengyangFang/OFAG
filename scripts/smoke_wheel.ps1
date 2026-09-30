param(
    [string]$PythonVersion = "3.11",
    [string]$Extras = "desktop,simpeg",
    [switch]$CoreOnly
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.TrimEnd('\')
$distribution = Join-Path $repository "dist"
$consumerBase = Join-Path $repository ".release-smoke"
$consumer = [IO.Path]::GetFullPath((Join-Path $consumerBase ([guid]::NewGuid().ToString("N"))))
if (-not $consumer.StartsWith($repository + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "The release smoke directory must stay inside the repository."
}

uv build --quiet --out-dir $distribution
if ($LASTEXITCODE -ne 0) { throw "Wheel build failed." }
$wheel = Get-ChildItem -LiteralPath $distribution -Filter "ofag-*.whl" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $wheel) { throw "Wheel build produced no wheel." }
$source = Get-ChildItem -LiteralPath $distribution -Filter "ofag-*.tar.gz" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $source) { throw "Build produced no source archive." }
& uv run --no-sync python (Join-Path $repository "scripts\check_wheel_contents.py") $wheel.FullName $source.FullName
if ($LASTEXITCODE -ne 0) { throw "Release archive contents check failed." }

try {
    uv venv $consumer --python $PythonVersion
    if ($LASTEXITCODE -ne 0) { throw "Consumer environment creation failed." }
    $python = Join-Path $consumer "Scripts\python.exe"
    $ofag = Join-Path $consumer "Scripts\ofag.exe"
    $package = $wheel.FullName
    if ($Extras -and -not $CoreOnly) { $package += "[$Extras]" }
    uv pip install --quiet --python $python $package
    if ($LASTEXITCODE -ne 0) { throw "Wheel installation failed." }

    Push-Location $consumer
    try {
        $report = & $ofag --json doctor --self-test | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $report.status -ne "ok" -or
            -not $report.runtime_self_test.passed) {
            throw "Installed-wheel worker self-test failed."
        }
        & $python -I -c "from ofag.agent.lessons import load_lessons; from ofag.agent.retrieval import default_index; from ofag.agent.replay import load_replays; assert load_lessons(); assert load_replays(); assert default_index(); print('Installed Agent knowledge loaded successfully')"
        if ($LASTEXITCODE -ne 0) { throw "Installed-wheel Agent knowledge test failed." }
    } finally {
        Pop-Location
    }
    Write-Host "Built $($wheel.Name) and passed a clean consumer install."
} finally {
    # Retry cleanup while Windows releases loaded extensions.
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        if (-not (Test-Path -LiteralPath $consumer)) { break }
        try {
            Remove-Item -LiteralPath $consumer -Recurse -Force -ErrorAction Stop
        } catch {
            if ($attempt -eq 8) { throw }
            Start-Sleep -Milliseconds 750
        }
    }
}
