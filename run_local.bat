@echo off
rem DepthWizard in local web mode: backend + viewer on http://127.0.0.1:8000; the browser opens
rem by itself once the model has loaded. Fallback for the desktop app. Needs the one-time setup
rem in README.md (Quickstart). Extra arguments go to scripts\serve.py, e.g. --port 8001.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The Python environment is missing. Follow the Quickstart in README.md first.
  pause
  exit /b 1
)
if not exist "viewer\dist\index.html" (
  echo The viewer is not built. Run: cd viewer ^&^& npm ci ^&^& npm run build
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\serve.py %*
