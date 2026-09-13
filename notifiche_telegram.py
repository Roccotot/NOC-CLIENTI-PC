"""
Notifiche Telegram per nuovi ticket e messaggi dei clienti.

Perché Telegram e non la posta: sulla rete del server le porte SMTP (465,
587, 25) risultano bloccate, mentre il traffico web normale (443) passa.
Telegram usa proprio la 443, quindi funziona dove la posta non arriva —
e in più l'avviso compare subito sul telefono.

Configurazione (variabili d'ambiente o file .env):

    TELEGRAM_TOKEN     codice del bot, ottenuto da @BotFather
    TELEGRAM_CHAT_ID   destinatario del messaggio
    APP_BASE_URL       url pubblico del sito, per i link ai ticket

Si imposta tutto con `python configura_telegram.py`.
Se manca la configurazione le notifiche vengono saltate in silenzio e il
sito continua a funzionare normalmente.
"""
import json
import os
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request

from config import carica_env

carica_env()

TOKEN        = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID      = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")

TIMEOUT = 15


def is_configured() -> bool:
    return bool(TOKEN and CHAT_ID)


def _api(metodo: str, dati: dict, token: str = "") -> dict:
    """Chiama l'API di Telegram e restituisce la risposta come dizionario."""
    url = f"https://api.telegram.org/bot{token or TOKEN}/{metodo}"
    corpo = urllib.parse.urlencode(dati).encode()
    richiesta = urllib.request.Request(url, data=corpo)
    with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as r:
        return json.load(r)


def _invia(testo: str) -> None:
    """Invio effettivo (bloccante). Chiamato dentro un thread."""
    try:
        risposta = _api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": testo,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
        if risposta.get("ok"):
            print("[telegram] Notifica inviata.")
        else:
            print(f"[telegram] Rifiutata: {risposta.get('description')}")
    except Exception:
        # Non deve mai bloccare il sito
        print("[telegram] ERRORE invio notifica:")
        traceback.print_exc()


def _invia_async(testo: str) -> None:
    if not is_configured():
        print("[telegram] Non configurato — notifica saltata.")
        return
    threading.Thread(target=_invia, args=(testo,), daemon=True).start()


def _esc(s) -> str:
    """Protegge i caratteri speciali dell'HTML di Telegram."""
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _link(problem_id: int) -> str:
    if not APP_BASE_URL:
        return ""
    return f"\n\n<a href=\"{APP_BASE_URL}/problems/{problem_id}\">Apri il ticket</a>"


def _taglia(testo: str, massimo: int = 500) -> str:
    testo = str(testo or "").strip()
    return testo if len(testo) <= massimo else testo[:massimo] + "…"


def notifica_nuovo_ticket(problem) -> None:
    """Avvisa che un cliente ha aperto un nuovo ticket."""
    emoji = {"Critico": "🔴", "Urgente": "🟠"}.get(problem.urgenza, "🟢")
    testo = (
        f"{emoji} <b>Nuovo ticket #{problem.id}</b>\n"
        f"<b>{_esc(problem.cinema)}</b>"
        f"{' — ' + _esc(problem.città) if problem.città else ''}\n"
        f"Sala {_esc(problem.sala)} · {_esc(problem.urgenza)}\n"
        f"Aperto da {_esc(problem.autore)}\n\n"
        f"{_esc(_taglia(problem.tipo))}"
        f"{_link(problem.id)}"
    )
    _invia_async(testo)


def notifica_nuovo_messaggio(problem, autore: str, testo_msg: str) -> None:
    """Avvisa che un cliente ha scritto un messaggio su un ticket."""
    testo = (
        f"💬 <b>Nuovo messaggio</b> — ticket #{problem.id}\n"
        f"<b>{_esc(problem.cinema)}</b> · Sala {_esc(problem.sala)}\n"
        f"Da {_esc(autore)}\n\n"
        f"{_esc(_taglia(testo_msg))}"
        f"{_link(problem.id)}"
    )
    _invia_async(testo)
