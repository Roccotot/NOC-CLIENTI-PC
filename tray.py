"""
Avvia SigraFilm NOC lasciando un'icona vicino all'orologio di Windows.

Serve per poter fermare il sito con un clic invece di andare a cercare
"pythonw.exe" nella Gestione attivita'.

Si avvia da solo con start_noc.bat o start_noc.vbs. A mano:
    pythonw tray.py

Librerie richieste (sono gia' in requirements.txt):
    pip install pystray pillow
"""
import os
import socket
import sys
import threading
import traceback
import webbrowser

CARTELLA = os.path.dirname(os.path.abspath(__file__))
PORTA = 5000

# In ascolto su tutte le schede di rete: il sito deve restare raggiungibile
# dagli altri computer e dai telefoni, non solo da questo PC.
ASCOLTO = "0.0.0.0"
INDIRIZZO_LOCALE = f"http://127.0.0.1:{PORTA}"

REGISTRO_ERRORI = os.path.join(CARTELLA, "errore_avvio.log")


# ── Messaggi a schermo ──────────────────────────────────
# Avviato con pythonw.exe non c'e' nessuna finestra nera: senza queste
# finestrelle un errore all'avvio sarebbe invisibile e il sito sembrerebbe
# semplicemente "non partito".

def _finestra(titolo: str, testo: str, icona: int = 0x40) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, testo, titolo, icona | 0x1000)
    except Exception:
        print(f"{titolo}\n{testo}")


def _avviso(titolo, testo):
    _finestra(titolo, testo, 0x30)      # punto esclamativo


def _errore(titolo, testo):
    _finestra(titolo, testo, 0x10)      # croce rossa


def _domanda(titolo: str, testo: str) -> bool:
    """True se l'utente risponde Si'. Se non si puo' chiedere, risponde Si'."""
    try:
        import ctypes
        # 4 = Si'/No, 0x20 = punto interrogativo, 6 = ha premuto Si'
        return ctypes.windll.user32.MessageBoxW(0, testo, titolo,
                                                4 | 0x20 | 0x1000) == 6
    except Exception:
        return True


def _registra_errore(intestazione: str) -> str:
    try:
        with open(REGISTRO_ERRORI, "a", encoding="utf-8") as f:
            f.write(f"\n===== {intestazione} =====\n")
            traceback.print_exc(file=f)
    except Exception:
        pass
    return REGISTRO_ERRORI


# ── Rete ────────────────────────────────────────────────

def _gia_avviato() -> bool:
    """
    Vero se qualcosa risponde gia' sulla porta del sito.

    Senza questo controllo un secondo doppio clic su start_noc.bat farebbe
    partire un processo che muore subito in silenzio, lasciando il dubbio
    su quale dei due sia quello buono.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def _indirizzo_in_rete() -> str:
    """
    Indirizzo con cui gli altri vedono questo PC, da mostrare nel menu.

    Il socket non manda niente: serve solo a farsi dire da Windows quale
    scheda di rete userebbe per uscire.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.6)
            s.connect(("8.8.8.8", 80))
            return f"http://{s.getsockname()[0]}:{PORTA}"
    except Exception:
        return INDIRIZZO_LOCALE


# ── Icona ───────────────────────────────────────────────

ROSSO_SIGRA = (230, 57, 70, 255)     # lo stesso rosso del sito

# Nomi dei caratteri in grassetto da provare, prima Windows poi Linux
CARATTERI = ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _carattere(dimensione):
    from PIL import ImageFont
    for nome in CARATTERI:
        try:
            return ImageFont.truetype(nome, dimensione)
        except Exception:
            continue
    return ImageFont.load_default()


def _immagine_icona():
    """
    Pallino rosso con la S bianca.

    Il logo SigraFilm non va bene qui: e' largo 187 e alto 109, quindi in un
    quadrato diventerebbe alto 9 pixel alla dimensione del vassoio e la
    scritta sarebbe illeggibile. Serve qualcosa che si riconosca a colpo
    d'occhio tra le altre icone vicino all'orologio.

    Si disegna in grande e si rimpicciolisce, cosi' i bordi restano puliti.
    """
    from PIL import Image, ImageDraw

    grande = 256
    lato = 64
    img = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    disegno = ImageDraw.Draw(img)
    disegno.ellipse([0, 0, grande - 1, grande - 1], fill=ROSSO_SIGRA)

    font = _carattere(int(grande * 0.72))
    disegno.text((grande / 2, grande / 2 + grande * 0.02), "S",
                 fill=(255, 255, 255, 255), font=font, anchor="mm")

    return img.resize((lato, lato), Image.LANCZOS)


# ── Server ──────────────────────────────────────────────

def _avvia_server():
    try:
        from app import app
        try:
            from waitress import serve
            serve(app, host=ASCOLTO, port=PORTA, threads=4)
        except ImportError:
            app.run(host=ASCOLTO, port=PORTA, debug=False, use_reloader=False)
    except Exception:
        percorso = _registra_errore("Errore durante l'avvio del sito")
        _errore("SigraFilm NOC - il sito non e' partito",
                "Il sito non e' riuscito ad avviarsi.\n\n"
                f"Il motivo e' scritto qui:\n{percorso}")
        os._exit(1)


def _attendi_fine_scritture(secondi: int = 5) -> None:
    """
    Aspetta che finisca un eventuale salvataggio prima di chiudere.

    I file Excel si salvano su un temporaneo e poi si rinominano, quindi una
    chiusura a meta' non rovina i dati: lascia pero' un file .tmp di scarto
    nella cartella data, e cosi' si evita anche quello.
    """
    try:
        import storage
        storage.attendi_scritture(secondi)
    except Exception:
        pass


# ── Voci del menu ───────────────────────────────────────

def _apri_sito(icona=None, voce=None):
    webbrowser.open(INDIRIZZO_LOCALE)


def _esci(icona, voce):
    if not _domanda("SigraFilm NOC",
                    "Vuoi fermare il sito?\n\n"
                    "Chi lo sta usando in questo momento non riuscira' piu' "
                    "ad aprirlo finche' non lo riavvii."):
        return
    icona.visible = False
    icona.stop()
    _attendi_fine_scritture()
    os._exit(0)


def main():
    if _gia_avviato():
        _avviso("SigraFilm NOC",
                "Il sito e' gia' avviato.\n\n"
                "Guarda l'icona vicino all'orologio, in basso a destra.\n"
                "Se non la vedi, premi la freccetta ^ per mostrare le icone "
                "nascoste.")
        return

    # Qualunque cosa vada storta con l'icona, il sito deve partire lo stesso:
    # meglio un sito acceso senza icona che nessun sito. Per questo si cattura
    # qualsiasi errore e non solo la libreria mancante.
    try:
        import pystray
        icona = _costruisci_icona(pystray)
    except Exception:
        percorso = _registra_errore("Icona vicino all'orologio non disponibile")
        _avviso("SigraFilm NOC - icona non disponibile",
                "Non sono riuscito a mettere l'icona vicino all'orologio.\n\n"
                "Il sito parte lo stesso, ma per fermarlo servira' la "
                "Gestione attivita'.\n\n"
                "Di solito basta installare le librerie: dal prompt dei "
                "comandi, nella cartella del sito,\n\n"
                "    python -m pip install pystray pillow\n\n"
                f"Il motivo preciso e' scritto in:\n{percorso}")
        _avvia_server()       # blocca qui: e' il sito che tiene vivo il processo
        return

    threading.Thread(target=_avvia_server, daemon=True).start()
    icona.run()


def _costruisci_icona(pystray):
    in_rete = _indirizzo_in_rete()
    return pystray.Icon(
        name="SigraFilm NOC",
        icon=_immagine_icona(),
        title=f"SigraFilm NOC - attivo su {in_rete}",
        menu=pystray.Menu(
            pystray.MenuItem("SigraFilm NOC - sito attivo", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Apri il sito", _apri_sito, default=True),
            pystray.MenuItem(f"Dagli altri PC: {in_rete}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ferma il sito ed esci", _esci),
        ),
    )


if __name__ == "__main__":
    main()
