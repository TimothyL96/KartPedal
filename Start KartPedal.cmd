@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B measurement\app.py
) else (
  python -B measurement\app.py
)
if errorlevel 1 (
  echo See OPERATING.md for the Python and Node requirements.
  pause
)

