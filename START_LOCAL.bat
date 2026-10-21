@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
 py -3 main.py
 if errorlevel 1 pause
 exit /b
)
python -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
 python main.py
 if errorlevel 1 pause
 exit /b
)
echo Python with Tkinter was not found.
echo Install Python 3.12 or newer from https://www.python.org/downloads/windows/
echo Use the official installer and enable Add Python to PATH and Tcl/Tk.
echo Reopen this launcher after installation.
pause
exit /b 1
