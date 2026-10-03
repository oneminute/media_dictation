@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

if not exist backups mkdir backups

%PY% -c "import sqlite3,datetime,pathlib; from storage import database_path; src=database_path(); ts=datetime.datetime.now().strftime('%%Y%%m%%d_%%H%%M%%S'); dst=pathlib.Path('backups')/('media_dictation_'+ts+'.db'); s=sqlite3.connect(src); d=sqlite3.connect(dst); s.backup(d); d.close(); s.close(); print('Database backup:', dst)"
if errorlevel 1 (
  echo Database backup failed.
  if /I not "%~1"=="/quiet" pause
  exit /b 1
)

if /I not "%~1"=="/quiet" pause
