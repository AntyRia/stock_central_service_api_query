@echo off
setlocal
set SCRIPT_DIR=%~dp0
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3.12 "%SCRIPT_DIR%build_release.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%SCRIPT_DIR%build_release.py" %*
  exit /b %ERRORLEVEL%
)
echo Python 3.12 launcher not found. Install Python 3.12 or run from a Python 3.12 environment. 1>&2
exit /b 1
