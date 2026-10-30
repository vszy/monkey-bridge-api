@echo off
echo ========================================================
echo Stopping ChatGPT API Bridge Server (Port 8000)
echo ========================================================
echo.
set FOUND=0
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo Terminating PID %%a listening on port 8000...
    taskkill /F /PID %%a >nul 2>&1
)

if "%FOUND%"=="0" (
    echo No active process found listening on port 8000.
) else (
    echo.
    echo [SUCCESS] Process on port 8000 terminated.
)

pause
