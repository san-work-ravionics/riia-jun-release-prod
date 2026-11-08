@echo off
title RITA dev server (port 8000)
cd /d "C:\Users\Sandeep\Documents\Work\code\riia-projects\riia-jun-release-prod"
echo Stopping anything already listening on port 8000...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /F /T /PID %%p >nul 2>&1
echo.
echo Starting RITA at http://localhost:8000
echo Close this window or press Ctrl+C to stop the server.
echo.
set "RITA_CHAT_EMBED_MODEL_PATH=C:\Users\Sandeep\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2\snapshots\c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
PYTHON START.PY
echo.
echo Server stopped.
pause
