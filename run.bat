@echo off
title Monkey Bridge - OpenAI API Bridge Server
echo =======================================================
echo    🐵 MONKEY BRIDGE - ChatGPT Web to OpenAI API Bridge
echo =======================================================
echo.

if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
    playwright install chromium
) else (
    call venv\Scripts\activate.bat
)

echo Starting Server on http://localhost:8000 ...
python app.py
pause
