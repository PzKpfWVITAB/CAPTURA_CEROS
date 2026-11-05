@echo off
chcp 65001 >nul
title Compilando Ejecutable Portable - CAPTURA_CEROS
cd /d "%~dp0"

echo ========================================================
echo   COMPILADOR DE EJECUTABLE PORTABLE (CAPTURA_CEROS.exe)
echo ========================================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual...
    python -m venv .venv
)

echo [2/3] Instalando dependencias necesarias (PyMuPDF, Pillow, PyInstaller)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [3/3] Generando ejecutable portable unico (CAPTURA_CEROS.exe)...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --exclude-module onnxruntime --exclude-module pymupdf4llm --exclude-module pymupdf_layout --exclude-module numpy --exclude-module networkx --name "CAPTURA_CEROS" app_captura.py

if exist "dist\CAPTURA_CEROS.exe" (
    copy /Y "dist\CAPTURA_CEROS.exe" "CAPTURA_CEROS.exe" >nul
    echo.
    echo ========================================================
    echo   EXITO: Se genero "CAPTURA_CEROS.exe" en esta carpeta
    echo ========================================================
) else (
    echo.
    echo [ERROR] No se pudo generar el ejecutable.
)
pause
