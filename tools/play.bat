@echo off
rem Start build\<folder>\game\default.xex in Xenia. usage: play.bat <folder> "<game name>"
rem Xenia: XENIA, else build\xenia.txt (if that path exists), else Documents\Xenia Canary.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
if not defined XENIA if exist "%ROOT%\build\xenia.txt" set /p XENIA=<"%ROOT%\build\xenia.txt"
if defined XENIA if not exist "%XENIA%" set "XENIA="
if not defined XENIA (
  for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "XENIA=%%D\Xenia Canary\xenia_canary.exe"
)
if not exist "%XENIA%" (
  echo Xenia Canary not found at "%XENIA%". Run setup.bat, or set XENIA to xenia_canary.exe.
  pause
  exit /b 1
)
if not exist "%ROOT%\build\%~1\game\default.xex" (
  echo %~2 is not set up yet. Run setup.bat with your %~2 files first.
  pause
  exit /b 1
)
start "" "%XENIA%" "%ROOT%\build\%~1\game\default.xex"
