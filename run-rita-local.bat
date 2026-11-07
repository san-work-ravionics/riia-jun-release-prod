@echo off
title RITA dev server (port 8000)
cd /d "C:\Users\Sandeep\Documents\Work\code\riia-projects\riia-jun-release-prod"
echo Stopping anything already listening on port 8000...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /F /T /PID %%p >nul 2>&1
echo.
echo Starting RITA at http://localhost:8000  (Jarvis: /dashboard/jarvis.html)
echo Close this window or press Ctrl+C to stop the server.
echo.
start "" /min cmd /c "timeout /t 8 >nul & start http://localhost:8000/dashboard/jarvis.html"
python start.py
echo.
echo Server stopped.
pause
