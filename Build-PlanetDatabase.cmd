@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-PlanetDatabase.ps1"
if errorlevel 1 (
	echo.
	echo Build failed. Review the error above.
	pause
	exit /b 1
)
