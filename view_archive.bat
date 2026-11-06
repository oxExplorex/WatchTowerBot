@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m archive_viewer %*
) else (
    py -3 -m archive_viewer %*
)
if errorlevel 1 pause
