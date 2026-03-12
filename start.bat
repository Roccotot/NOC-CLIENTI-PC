@echo off
title SigraFilm NOC — Server
echo.
echo  ================================
echo   SigraFilm NOC - Avvio server
echo  ================================
echo.

:: Controlla se Python e' installato
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERRORE] Python non trovato.
    echo  Scaricalo da https://www.python.org/downloads/
    echo  Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)

:: Installa dipendenze se necessario
if not exist "venv\" (
    echo  Creazione ambiente virtuale...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo  Installazione dipendenze...
pip install -r requirements.txt --quiet

:: Crea cartella data se non esiste
if not exist "data\" (
    mkdir data
    echo  Cartella data\ creata.
)

echo.
echo  Server in avvio su http://localhost:5000
echo  Premi CTRL+C per fermare il server.
echo.

:: Avvia con waitress (server WSGI stabile per Windows)
python -c "from waitress import serve; from app import app; print('Avviato!'); serve(app, host='0.0.0.0', port=5000, threads=4)"

pause
