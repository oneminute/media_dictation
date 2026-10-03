@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

echo Creating full Media Dictation backup...
echo This includes SQLite and locally uploaded media.
echo.
%PY% backup_full.py
if errorlevel 1 (
  echo.
  echo Full backup failed.
  pause
  exit /b 1
)
echo.
pause
