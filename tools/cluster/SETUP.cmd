@echo off
setlocal
pushd "%~dp0" || exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_worker_access.ps1" -BundleDirectory "%CD%" %*
set "setup_result=%ERRORLEVEL%"
if not "%setup_result%"=="0" echo Setup failed. Please copy the error above to the controller.
popd
if /I not "%~1"=="-ValidateOnly" pause
exit /b %setup_result%
