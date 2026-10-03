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
echo Checking production dependencies...
%PY% -c "import flask, waitress, openai, dotenv, youtube_transcript_api" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Dependencies are missing. Run setup_windows.bat first.
  pause
  exit /b 1
)

if exist "backup_data_windows.bat" call "backup_data_windows.bat" /quiet

echo.
echo Checking local Ollama...
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; Write-Host '  Ollama: AVAILABLE at http://127.0.0.1:11434' -ForegroundColor Green } catch { Write-Host '  Ollama: NOT AVAILABLE - auto mode will use OpenAI fallback if configured.' -ForegroundColor Yellow }"

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
