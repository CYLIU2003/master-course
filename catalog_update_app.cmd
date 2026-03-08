@echo off
setlocal
set "REPO_ROOT=%~dp0"
if exist "%REPO_ROOT%.venv\Scripts\python.exe" (
  "%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%catalog_update_app.py" %*
) else (
  python "%REPO_ROOT%catalog_update_app.py" %*
)
endlocal
