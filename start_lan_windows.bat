@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  set "PY=python"
)

echo ============================================================
echo Media Dictation - LAN Production Server
echo ============================================================
echo.
echo Installing/checking required packages...
%PY% -m pip install -U -r requirements.txt
if errorlevel 1 (
  echo.
  echo Failed to install Python dependencies.
  pause
  exit /b 1
)

echo.
echo Server port: 8765
echo.
echo Open on THIS computer:
echo   http://127.0.0.1:8765
echo.
echo Open on another computer on the SAME Wi-Fi/LAN:
powershell -NoProfile -Command "$configs = Get-NetIPConfiguration ^| Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.IPv4Address -ne $null }; if (-not $configs) { Write-Host '  Could not detect a LAN IPv4 address. Run ipconfig and use your IPv4 Address.' } else { $configs ^| ForEach-Object { $_.IPv4Address.IPAddress } ^| Sort-Object -Unique ^| ForEach-Object { Write-Host ('  http://' + $_ + ':8765') } }"
echo.
echo IMPORTANT:
echo   - Both computers must be on the same local network.
echo   - If Windows Firewall asks, allow Python on PRIVATE networks.
echo   - Keep this window open while the child is practicing.
echo   - Press Ctrl+C here to stop the server.
echo.
echo Starting production server with Waitress...
echo.

start "" http://127.0.0.1:8765

%PY% -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=8765, threads=8)"

echo.
echo Server stopped.
pause
