@echo off
title SigraFilm NOC - Configurazione email
cd /d "%~dp0"

echo.
echo  ==========================================
echo   SigraFilm NOC - Configurazione notifiche
echo  ==========================================
echo.

:: Python installato per l'utente Sigrafilm (lo stesso usato dal sito)
set "PY=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe"

:: Se non c'e', prova con quello nel PATH
if not exist "%PY%" set "PY=python"

"%PY%" configura_email.py

echo.
echo  Premi un tasto per chiudere.
pause >nul
