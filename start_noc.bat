@echo off
:: Avvia il sito in background, senza finestra.
:: Usa %~dp0 (la cartella di questo file) invece di un percorso fisso,
:: cosi' continua a funzionare anche se sposti o rinomini la cartella.
cd /d "%~dp0"

set "PYW=C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

start "" "%PYW%" main.py
exit
