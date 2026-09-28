@echo off
rem Build a standalone Windows GUI executable. The model engine and downloaded weights remain separate.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run START-HERE.bat once to create the Strata Python environment before building.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6,<7"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name StrataDesktop --paths desktop desktop\app.py
if errorlevel 1 exit /b 1
echo.
echo Built: dist\StrataDesktop\StrataDesktop.exe
echo Keep the entire dist\StrataDesktop folder together, not just the EXE.
pause
