@echo off
setlocal
rem Build the mod and install it into Xenia Canary. You can also drag the
rem folder with your game files (or the files) onto this file.
cd /d "%~dp0"
set "PY="
set "CHECK=import sys; sys.exit(sys.version_info < (3, 8))"
py -3 -c "%CHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "%CHECK%" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.8 or newer is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt || (
  echo Could not install the Python packages NumPy and Pillow.
  pause
  exit /b 1
)
%PY% tools\setup_mod.py %*
pause
