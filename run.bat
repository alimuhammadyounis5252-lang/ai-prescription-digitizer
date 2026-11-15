@echo off
rem Starts the AI Prescription Digitizer on Windows. Double-click this file.
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet -r requirements.txt
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo  A .env file was created. Open it, add your model key, then run this file again.
    echo.
)
python app.py
pause
