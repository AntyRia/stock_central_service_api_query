@echo off
setlocal
set SCRIPT_DIR=%~dp0
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%SCRIPT_DIR%upload_release.py" %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT_DIR%upload_release.py" %*
  exit /b %ERRORLEVEL%
)
echo python launcher not found. Install Python 3 and ensure py or python is on PATH. 1>&2
exit /b 1
