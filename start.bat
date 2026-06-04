@echo off
setlocal
cd /d "%~dp0"

python -X utf8 main.py
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" (
    echo.
    echo Bot stopped with error code %exit_code%. Check the latest log file for details.
    pause
)
exit /b %exit_code%
