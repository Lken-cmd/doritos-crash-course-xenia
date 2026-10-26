@echo off
setlocal
rem Set up the mods (setup window). Drop game files on it; "--console" for no window.
cd /d "%~dp0"
if not exist "tools\setup_mod.py" (
  echo Unpack the whole zip file first ^(right-click it, Extract All^), then run setup.bat
  echo from the unpacked folder.
  pause
  exit /b 1
)
set "PY="
set "HAS_TK="
set "CHECK=import sys; sys.exit(sys.version_info < (3, 8))"
rem Prefer a Python with tkinter (optional in the installer: "tcl/tk and IDLE").
py -3 -c "import tkinter; %CHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import tkinter; %CHECK%" >nul 2>nul && set "PY=python"
if defined PY set "HAS_TK=1"
if not defined PY py -3 -c "%CHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "%CHECK%" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.8 or newer is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)
echo Preparing the setup (installing the Python packages NumPy and Pillow)...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt || (
  echo Could not install the Python packages NumPy and Pillow.
  pause
  exit /b 1
)
if /i "%~1"=="--console" goto console
if not defined HAS_TK goto console_with_files
echo The setup window is open. This window closes with it.
%PY% tools\setup_gui.py %* || pause
exit /b
:console_with_files
echo Your Python can't show the setup window (it was installed without "tcl/tk and
echo IDLE"), so the setup runs here instead.
echo.
%PY% tools\setup_mod.py %*
pause
exit /b
:console
%PY% tools\setup_mod.py
pause
