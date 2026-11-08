@echo off
rem Launch BotOffice on Windows without needing Git Bash or WSL.
rem Double-click this file, or run:  scripts\run.bat
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"
set "VENV=%ROOT%\.venv"

rem 1. Create the virtual environment on first run.
if not exist "%VENV%" (
  echo Creating the virtual environment...
  where uv >nul 2>nul
  if errorlevel 1 (
    python -m venv "%VENV%"
  ) else (
    uv venv "%VENV%"
  )
)

set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" set "PY=%VENV%\bin\python"

if not exist "%PY%" (
  echo Could not find Python inside the virtual environment.
  pause
  exit /b 1
)

rem 2. Install dependencies if any of them are missing.
"%PY%" -c "import PySide6, fastapi, uvicorn, httpx, yaml" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  where uv >nul 2>nul
  if errorlevel 1 (
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install "PySide6==6.12.0" httpx fastapi uvicorn pyyaml
  ) else (
    uv pip install --python "%PY%" "PySide6==6.12.0" httpx fastapi uvicorn pyyaml
  )
  if errorlevel 1 goto :error
)

rem 3. --check verifies the setup without opening the window, so this file
rem    can be tested by a script.
if /I "%~1"=="--check" (
  echo Setup OK: %PY%
  exit /b 0
)

echo Starting BotOffice...
"%PY%" -m botoffice.gui
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo BotOffice failed to start. The message above says why.
pause
exit /b 1
