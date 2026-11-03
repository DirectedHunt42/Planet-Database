$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $root 'build'

function Test-QtPrefix([string]$path) {
	if ([string]::IsNullOrWhiteSpace($path)) {
		return $false
	}

	return Test-Path (Join-Path $path 'lib\cmake\Qt6\Qt6Config.cmake')
}

$qtPrefix = $null

if ($env:CMAKE_PREFIX_PATH) {
	foreach ($path in ($env:CMAKE_PREFIX_PATH -split ';')) {
		if (Test-QtPrefix $path) {
			$qtPrefix = $path
			break
		}
	}
}

if (-not $qtPrefix -and (Test-Path 'C:\Qt')) {
	$qtCandidates = Get-ChildItem 'C:\Qt' -Directory -ErrorAction SilentlyContinue |
		ForEach-Object { Get-ChildItem $_.FullName -Directory -ErrorAction SilentlyContinue } |
		Where-Object { Test-QtPrefix $_.FullName } |
		Sort-Object FullName -Descending

	if ($qtCandidates) {
		$qtPrefix = $qtCandidates[0].FullName
	}
}

if (-not $qtPrefix) {
	Write-Error 'Qt 6 was not found. Install Qt with the MSVC 2022 64-bit component, or set CMAKE_PREFIX_PATH to the Qt installation directory.'
	exit 1
}

Write-Host "Using Qt: $qtPrefix"
Write-Host 'Configuring project...'
cmake -S $root -B $build "-DCMAKE_PREFIX_PATH=$qtPrefix"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'Building Release configuration...'
cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$executable = Join-Path $build 'Release\PlanetDatabase.exe'
Write-Host "Build succeeded: $executable" -ForegroundColor Green
Write-Host 'Press Enter to close.'
Read-Host
