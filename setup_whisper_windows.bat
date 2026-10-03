@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

echo ============================================================
echo Media Dictation - Optional Whisper Setup
echo ============================================================
echo.
echo Installing faster-whisper and its dependencies...
%PY% -m pip install -U -r requirements-whisper.txt
if errorlevel 1 goto :fail

echo.
echo Verifying faster-whisper import...
%PY% -c "import faster_whisper; print('faster-whisper:', faster_whisper.__version__)"
if errorlevel 1 goto :fail

echo.
echo Running project tests...
%PY% -m unittest discover -s tests -v
if errorlevel 1 goto :fail

echo.
echo Whisper setup complete.
echo.
echo Recommended .env settings for this PC:
echo   WHISPER_MODEL=small.en
echo   WHISPER_DEVICE=auto
echo   WHISPER_DOWNLOAD_ROOT=E:/AI/whisper-models
echo   MEDIA_DICTATION_MEDIA_DIR=E:/AI/media-dictation-media
echo.
echo In auto mode the app tries CUDA first and falls back to CPU int8.
pause
exit /b 0

:fail
echo.
echo Whisper setup or tests failed. Review the messages above.
pause
exit /b 1
