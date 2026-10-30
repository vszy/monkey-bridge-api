@echo off
title Aider - AI Pair Programmer
echo ========================================================
echo    🐵 AIDER - Connected to Monkey Bridge API
echo ========================================================
echo.

set OPENAI_API_BASE=http://localhost:8000/v1
set OPENAI_API_KEY=not-needed
set PATH=%APPDATA%\Python\Python310\Scripts;%PATH%

echo Connecting to Monkey Bridge at http://localhost:8000/v1 ...
echo Model: openai/gpt-4o
echo.

aider --openai-api-base http://localhost:8000/v1 --model openai/gpt-4o --no-stream %*
