@echo off
rem Open the native Windows manager (or its packaged EXE, when available).
setlocal
cd /d "%~dp0"
if exist "dist\StrataDesktop\StrataDesktop.exe" (
    start "" "%~dp0dist\StrataDesktop\StrataDesktop.exe"
    exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop\app.py"
    exit /b 0
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0desktop\app.py"
    exit /b 0
)
echo Python is needed for the source launcher. Run START-HERE.bat first, or use BUILD-DESKTOP.bat for an EXE.
pause
exit /b 1
