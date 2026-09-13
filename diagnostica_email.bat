@echo off
title SigraFilm NOC - Diagnostica posta
cd /d "%~dp0"

echo.
echo  ==========================================
echo   SigraFilm NOC - Diagnostica posta
echo  ==========================================
echo.

set "PY=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" diagnostica_email.py

echo.
echo  Premi un tasto per chiudere.
pause >nul
