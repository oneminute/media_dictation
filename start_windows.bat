@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  set "PY=python"
)

echo Installing/checking required packages...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Failed to install Python dependencies.
  pause
  exit /b 1
)

echo.
echo Starting Media Dictation at http://127.0.0.1:8765
start "" http://127.0.0.1:8765
%PY% app.py

pause
