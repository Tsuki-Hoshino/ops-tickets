@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 goto no_python

echo [2/3] Checking dependencies...
python -c "import flask, waitress, openpyxl, docx, PIL, requests" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies, this may take a few minutes...
    python -m pip install -r requirements.txt
    if errorlevel 1 goto no_deps
)

echo [3/3] Starting service...
python run.py --open-browser
echo.
echo Service stopped.
pause
exit /b 0

:no_python
echo.
echo Python not found. Please install Python 3.10 or later,
echo and check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:no_deps
echo.
echo Failed to install dependencies. Check the network, or run manually:
echo     python -m pip install -r requirements.txt
echo.
pause
exit /b 1
