@echo off
chcp 65001 >nul
title Generador de Carpeta Portable - CAPTURA_CEROS_PORTABLE
cd /d "%~dp0"

echo ====================================================================
echo   EMPAQUETADOR DE CARPETA 100%% PORTABLE (CAPTURA_CEROS_PORTABLE)
echo ====================================================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creando entorno virtual...
    python -m venv .venv
)

echo [2/4] Verificando dependencias (PyMuPDF, Pillow, PyMySQL, PyInstaller)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [3/4] Compilando carpeta autocontenida (--onedir) sin dependencias externas...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --windowed ^
    --exclude-module onnxruntime ^
    --exclude-module pymupdf4llm ^
    --exclude-module pymupdf_layout ^
    --exclude-module numpy ^
    --exclude-module networkx ^
    --add-binary "C:\Windows\System32\vcruntime140.dll;." ^
    --add-binary "C:\Windows\System32\vcruntime140_1.dll;." ^
    --add-binary "C:\Windows\System32\msvcp140.dll;." ^
    --add-binary "C:\Windows\System32\msvcp140_1.dll;." ^
    --add-binary "C:\Windows\System32\msvcp140_2.dll;." ^
    --name "CAPTURA_CEROS" app_captura.py

echo [4/4] Preparando carpeta final "CAPTURA_CEROS_PORTABLE"...
if exist "CAPTURA_CEROS_PORTABLE" (
    rmdir /S /Q "CAPTURA_CEROS_PORTABLE"
)
xcopy "dist\CAPTURA_CEROS" "CAPTURA_CEROS_PORTABLE\" /E /I /H /Y >nul
mkdir "CAPTURA_CEROS_PORTABLE\data" 2>nul
copy /Y "README.md" "CAPTURA_CEROS_PORTABLE\LEEME_Y_ESTRUCTURA_MYSQL.md" >nul

echo.
echo ====================================================================
echo   EXITO: La carpeta "CAPTURA_CEROS_PORTABLE" esta lista para
echo   copiarse a cualquier PC sin instalar Python ni librerias externas.
echo ====================================================================
pause
