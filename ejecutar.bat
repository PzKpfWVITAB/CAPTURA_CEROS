@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "CAPTURA_CEROS.exe" (
    start "" "CAPTURA_CEROS.exe"
    exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" app_captura.py
) else (
    python app_captura.py
)
