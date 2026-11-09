@echo off
cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

rem --- Virtuelle Umgebung pruefen / anlegen ---
if not exist "%PY%" (
    echo Keine virtuelle Umgebung gefunden - lege "%VENV%" an ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo FEHLER: venv konnte nicht erstellt werden.
        echo Ist Python 3 installiert und "Add Python to PATH" angehakt?
        pause
        exit /b 1
    )
    if exist "%VENV%\requirements.installed" del "%VENV%\requirements.installed"
)

rem --- Pakete nur installieren, wenn neu oder requirements.txt geaendert ---
fc /b requirements.txt "%VENV%\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installiere Pakete in "%VENV%" ...
    "%PY%" -m pip install -q --upgrade pip
    "%PY%" -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo FEHLER: Pakete konnten nicht installiert werden.
        pause
        exit /b 1
    )
    copy /y requirements.txt "%VENV%\requirements.installed" >nul
)

start "" http://localhost:5000
"%PY%" app.py
pause
