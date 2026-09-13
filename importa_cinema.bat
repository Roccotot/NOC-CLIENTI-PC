@echo off
title SigraFilm NOC - Importa cinema
cd /d "%~dp0"

echo.
echo  ==========================================
echo   SigraFilm NOC - Importa cinema reali
echo  ==========================================
echo.

set "PY=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" importa_cinema.py

echo.
echo  Premi un tasto per chiudere.
pause >nul
