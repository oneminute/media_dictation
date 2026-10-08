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
if not defined OLLAMA_HOST set "OLLAMA_HOST=127.0.0.1:12000"
set "OLLAMA_BASE_URL=http://%OLLAMA_HOST%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_ollama_windows.ps1"
if errorlevel 1 (
  echo   OpenAI fallback can still be used when configured.
)

echo.
echo Server port: 8765
echo.
echo Open on THIS computer:
echo   http://127.0.0.1:8765
echo.
echo Open on another computer on the SAME Wi-Fi/LAN:
powershell -NoProfile -Command "$found=$false; foreach($cfg in Get-NetIPConfiguration){ if($null -ne $cfg.IPv4DefaultGateway -and $null -ne $cfg.IPv4Address){ foreach($addr in $cfg.IPv4Address){ if($addr.IPAddress){ Write-Host ('  http://' + $addr.IPAddress + ':8765'); $found=$true } } } }; if(-not $found){ Write-Host '  Could not detect a LAN IPv4 address. Run ipconfig and use your IPv4 Address.' }"
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
