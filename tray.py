"""
Avvia SigraFilm NOC con icona nel system tray di Windows.

Utilizzo:
    python tray.py

Dipendenze extra:
    pip install pystray pillow
"""
import threading
import webbrowser
import os
import sys

import pystray
from PIL import Image, ImageDraw


HOST = "127.0.0.1"
PORT = 5000
URL  = f"http://{HOST}:{PORT}"


# ── Icona tray ──────────────────────────────────────────
def _make_icon() -> Image.Image:
    """
    Prova a caricare il logo del progetto ridimensionato a 64x64.
    Se non disponibile, genera un'icona verde con la lettera S.
    """
    logo_path = os.path.join(os.path.dirname(__file__), "static", "logo_sigra.png")
    if os.path.isfile(logo_path):
        try:
            img = Image.open(logo_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
            return img
        except Exception:
            pass

    # Fallback: cerchio verde con "S"
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=(63, 185, 80, 255))
    draw.text((size // 2 - 7, size // 2 - 10), "S", fill="white")
    return img


# ── Server Flask/Waitress ────────────────────────────────
def _run_server():
    from app import app
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=4)
    except ImportError:
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


# ── Menu tray ───────────────────────────────────────────
def _open_browser(icon, item):
    webbrowser.open(URL)


def _quit(icon, item):
    icon.stop()
    os._exit(0)


def main():
    # Avvia il server in un thread daemon
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    icon = pystray.Icon(
        name="SigraFilm NOC",
        icon=_make_icon(),
        title="SigraFilm NOC — attivo",
        menu=pystray.Menu(
            pystray.MenuItem("SigraFilm NOC", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🌐 Apri nel browser", _open_browser, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Esci", _quit),
        ),
    )

    print(f"SigraFilm NOC — avviato su {URL}")
    print("Icona attiva nel system tray. Doppio clic per aprire il browser.")
    icon.run()


if __name__ == "__main__":
    main()
