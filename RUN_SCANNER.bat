@echo off
setlocal
title HP Government Jobs Finder - Scanner
cd /d "%~dp0"

echo =====================================
echo    HP GOVT JOBS FINDER SCANNER
echo =====================================
echo.

if not exist "scripts" mkdir "scripts"
if not exist "jobs.js" (
    echo ERROR: jobs.js database nahi mili. Existing data untouched.
    pause
    exit /b 1
)

echo Downloading latest fixed scanner from GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/kartiksharma479-vasu/hp-govt-jobs-finder/main/scripts/auto_update_hppsc.py' -OutFile 'scripts\auto_update_hppsc.py' -UseBasicParsing; exit 0 } catch { Write-Host $_; exit 1 }"
if errorlevel 1 (
    echo ERROR: Scanner download failed. Internet connection check karo.
    pause
    exit /b 1
)

findstr /c:"def parse_jobs_js_array" "scripts\auto_update_hppsc.py" >nul
if errorlevel 1 (
    echo ERROR: Downloaded scanner verification failed. Not running.
    pause
    exit /b 1
)

echo Updated scanner verified. Starting...
echo.
python "scripts\auto_update_hppsc.py"

echo.
echo =====================================
echo Scanner finished. Check output above.
echo =====================================
pause
