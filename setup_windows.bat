@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

echo ============================================================
echo Media Dictation - Windows Setup / Update
echo ============================================================
echo.
%PY% -m pip install -U pip
if errorlevel 1 goto :fail

%PY% -m pip install -U -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Running unit tests...
%PY% -m unittest discover -s tests -v
if errorlevel 1 goto :fail

echo.
echo Setup complete. You can now run:
echo   start_windows.bat
echo or:
echo   start_production_windows.bat
echo.
pause
exit /b 0

:fail
echo.
echo Setup or tests failed. Review the messages above.
pause
exit /b 1
