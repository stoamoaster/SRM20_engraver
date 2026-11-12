@echo off
cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

rem --- Virtuelle Umgebung pruefen / anlegen ---
if not exist "%PY%" (
    echo No virtual environment found - creating "%VENV%" ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo ERROR: venv could not be created.
        echo Is Python 3 installed with "Add Python to PATH" ticked?
        pause
        exit /b 1
    )
    if exist "%VENV%\requirements.installed" del "%VENV%\requirements.installed"
)

rem --- Pakete nur installieren, wenn neu oder requirements.txt geaendert ---
fc /b requirements.txt "%VENV%\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing packages into "%VENV%" ...
    "%PY%" -m pip install -q --upgrade pip
    "%PY%" -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: packages could not be installed.
        pause
        exit /b 1
    )
    copy /y requirements.txt "%VENV%\requirements.installed" >nul
)

start "" http://localhost:5000
"%PY%" app.py
pause
