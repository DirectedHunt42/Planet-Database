param(
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$mainScript = Join-Path $projectRoot "main.py"
$iconPath = Join-Path $projectRoot "icons\planet-database.ico"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $downloadsDirectory = Join-Path $env:USERPROFILE "Downloads"
    $OutputDirectory = Join-Path $downloadsDirectory "Planet Database"
}

$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$outputParent = Split-Path -Parent $OutputDirectory

if (-not (Test-Path -LiteralPath $mainScript -PathType Leaf)) {
    throw "Application entry point was not found: $mainScript"
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Application icon was not found: $iconPath"
}
if (Test-Path -LiteralPath $OutputDirectory) {
    throw "Output folder already exists; move or rename it before building: $OutputDirectory"
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw "Python was not found on PATH. Install Python and reopen PowerShell."
}

& $pythonCommand.Source -c "import customtkinter, darkdetect"
if ($LASTEXITCODE -ne 0) {
    throw "The active Python environment is missing app dependencies. Run: python -m pip install -r requirements.txt"
}

& $pythonCommand.Source -c "import nuitka"
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka is not installed for the active Python environment. Run: python -m pip install nuitka"
}

$null = New-Item -ItemType Directory -Path $outputParent -Force
$buildDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "PlanetDatabase-Nuitka-" + [guid]::NewGuid().ToString("N")
)
$stagingDirectory = Join-Path $outputParent (
    ".PlanetDatabase-build-" + [guid]::NewGuid().ToString("N")
)

try {
    $null = New-Item -ItemType Directory -Path $buildDirectory
    $nuitkaArguments = @(
        "-m"
        "nuitka"
        "--mode=standalone"
        "--enable-plugin=tk-inter"
        "--include-package-data=customtkinter"
        "--windows-console-mode=disable"
        "--windows-icon-from-ico=$iconPath"
        "--include-data-files=$iconPath=icons/planet-database.ico"
        "--output-dir=$buildDirectory"
        "--output-filename=PlanetDatabase.exe"
        $mainScript
    )

    & $pythonCommand.Source @nuitkaArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka compilation failed with exit code $LASTEXITCODE. Check the compiler diagnostics above."
    }

    $distributionDirectories = @(
        Get-ChildItem -LiteralPath $buildDirectory -Directory |
            Where-Object { $_.Name.EndsWith(".dist", [System.StringComparison]::OrdinalIgnoreCase) }
    )
    if ($distributionDirectories.Count -ne 1) {
        throw "Expected one Nuitka standalone .dist folder, found $($distributionDirectories.Count)."
    }

    $distributionDirectory = $distributionDirectories[0].FullName
    $executablePath = Join-Path $distributionDirectory "PlanetDatabase.exe"
    if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
        throw "Nuitka output executable was not found: $executablePath"
    }

    $null = New-Item -ItemType Directory -Path $stagingDirectory
    Copy-Item -Path (Join-Path $distributionDirectory "*") `
        -Destination $stagingDirectory -Recurse

    $stagedIcon = Join-Path $stagingDirectory "icons\planet-database.ico"
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $stagedIcon) -Force
    Copy-Item -LiteralPath $iconPath -Destination $stagedIcon -Force

    Move-Item -LiteralPath $stagingDirectory -Destination $OutputDirectory
    Write-Host "Build complete: $OutputDirectory"
    Write-Host "Run: $(Join-Path $OutputDirectory 'PlanetDatabase.exe')"
}
finally {
    if (Test-Path -LiteralPath $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}
