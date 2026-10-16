@echo off
setlocal
rem Launch the modded game (run setup.bat first). XENIA, if set, overrides
rem the Xenia that setup.bat found.
if not defined XENIA if exist "%~dp0build\xenia.txt" set /p XENIA=<"%~dp0build\xenia.txt"
if not defined XENIA (
  for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "XENIA=%%D\Xenia Canary\xenia_canary.exe"
)
if not exist "%XENIA%" (
  echo Xenia Canary not found at "%XENIA%". Run setup.bat, or set XENIA to xenia_canary.exe.
  pause
  exit /b 1
)
start "" "%XENIA%" "%~dp0build\game\default.xex"
