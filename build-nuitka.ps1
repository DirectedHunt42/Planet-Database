param(
    [string]$OutputDirectory,
    [string]$InnoSetupCompiler,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$mainScript = Join-Path $projectRoot "main.py"
$iconPath = Join-Path $projectRoot "icons\planet-database.ico"
$projectFileIconPath = Join-Path $projectRoot "icons\planetdata-file-icon.ico"
$licensePath = Join-Path $projectRoot "LICENSE.txt"
$setupScript = Join-Path $projectRoot "Setup.iss"
$installerIconPath = Join-Path $projectRoot "icons\Installer.ico"

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
if (-not (Test-Path -LiteralPath $projectFileIconPath -PathType Leaf)) {
    throw "Project file icon was not found: $projectFileIconPath"
}
if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
    throw "License file was not found: $licensePath"
}
if (-not $SkipInstaller) {
    if (-not (Test-Path -LiteralPath $setupScript -PathType Leaf)) {
        throw "Inno Setup script was not found: $setupScript"
    }
    if (-not (Test-Path -LiteralPath $installerIconPath -PathType Leaf)) {
        throw "Installer icon was not found: $installerIconPath"
    }

    if ([string]::IsNullOrWhiteSpace($InnoSetupCompiler)) {
        $compilerCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($null -ne $compilerCommand) {
            $InnoSetupCompiler = $compilerCommand.Source
        } else {
            $compilerCandidates = @(
                "D:\Inno Setup 7\ISCC.exe",
                (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"),
                (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
                (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
            )
            $InnoSetupCompiler = $compilerCandidates |
                Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
                Select-Object -First 1
        }
    }
    if (
        [string]::IsNullOrWhiteSpace($InnoSetupCompiler) -or
        -not (Test-Path -LiteralPath $InnoSetupCompiler -PathType Leaf)
    ) {
        throw "Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 7 or 6, or pass -InnoSetupCompiler; use -SkipInstaller to build only the standalone app."
    }
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
    $stagedProjectFileIcon = Join-Path $stagingDirectory "icons\planetdata-file-icon.ico"
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $stagedIcon) -Force
    Copy-Item -LiteralPath $iconPath -Destination $stagedIcon -Force
    Copy-Item -LiteralPath $projectFileIconPath -Destination $stagedProjectFileIcon -Force
    Copy-Item -LiteralPath $licensePath -Destination (Join-Path $stagingDirectory "LICENSE.txt") -Force

    Move-Item -LiteralPath $stagingDirectory -Destination $OutputDirectory
    Write-Host "Build complete: $OutputDirectory"
    Write-Host "Run: $(Join-Path $OutputDirectory 'PlanetDatabase.exe')"

    if (-not $SkipInstaller) {
        $installerArguments = @(
            "/DBuildOutputDir=`"$OutputDirectory`""
            $setupScript
        )
        & $InnoSetupCompiler @installerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
        }
        Write-Host "Installer compilation complete."
    }
}
finally {
    if (Test-Path -LiteralPath $buildDirectory) {
        Remove-Item -LiteralPath $buildDirectory -Recurse -Force
    }
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}
