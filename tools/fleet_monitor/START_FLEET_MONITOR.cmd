@echo off
rem Read-only monitor page for the lab PCs, the thesis queue and the lab gateway.
rem Open http://127.0.0.1:8897/ on this PC. Extra arguments go to the server (for example --thesis-db PATH).
cd /d C:\master-course
C:\master-course\.venv\Scripts\python.exe -m tools.fleet_monitor.server %*
