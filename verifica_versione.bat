@echo off
title SigraFilm NOC - Verifica installazione
cd /d "%~dp0"
echo.
set "PY=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" verifica_versione.py
echo.
echo  Premi un tasto per chiudere.
pause >nul
