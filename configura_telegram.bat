@echo off
title SigraFilm NOC - Notifiche Telegram
cd /d "%~dp0"

echo.
echo  ==========================================
echo   SigraFilm NOC - Notifiche Telegram
echo  ==========================================
echo.

set "PY=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" configura_telegram.py

echo.
echo  Premi un tasto per chiudere.
pause >nul
