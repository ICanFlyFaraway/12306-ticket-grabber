@echo off
cd /d "%~dp0"
set TICKET_MOCK=1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
)
pause
