@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py"
) else (
  set "PY=python"
)

echo Checking dependencies...
%PY% -c "import flask, openai, dotenv, youtube_transcript_api" >nul 2>nul
if errorlevel 1 (
  echo Dependencies are missing. Run setup_windows.bat first.
  pause
  exit /b 1
)

echo.
if not defined OLLAMA_HOST set "OLLAMA_HOST=127.0.0.1:12000"
set "OLLAMA_BASE_URL=http://%OLLAMA_HOST%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_ollama_windows.ps1"
if errorlevel 1 (
  echo.
  echo Local Ollama is unavailable. OpenAI fallback can still be used when configured.
)

echo.
echo Starting Media Dictation at http://127.0.0.1:8765
start "" http://127.0.0.1:8765
%PY% app.py

pause
