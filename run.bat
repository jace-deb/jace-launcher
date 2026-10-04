@echo off
rem Start Jace Launcher from source on Windows (creates the virtualenv on first run).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\pythonw -m jace %*
