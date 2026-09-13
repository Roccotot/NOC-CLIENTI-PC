"""
Configurazione guidata delle notifiche Telegram.

Da eseguire sul PC dove gira il sito:

    python configura_telegram.py

Spiega come creare il bot, trova da solo il destinatario, invia un
messaggio di prova e salva la configurazione nel file .env.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PERCORSO_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
TIMEOUT = 15


def api(token: str, metodo: str, dati: dict = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{metodo}"
    corpo = urllib.parse.urlencode(dati or {}).encode()
    richiesta = urllib.request.Request(url, data=corpo)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Telegram risponde con un JSON anche quando rifiuta
        try:
            return json.load(e)
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        # Rete bloccata, DNS, firewall: messaggio chiaro invece di un crash
        return {"ok": False, "_rete": True,
                "description": f"impossibile raggiungere Telegram ({type(e).__name__})"}


def verifica_rete() -> bool:
    """Controlla che api.telegram.org sia raggiungibile prima di iniziare."""
    try:
        with urllib.request.urlopen("https://api.telegram.org", timeout=TIMEOUT):
            return True
    except urllib.error.HTTPError:
        return True      # risponde: va bene lo stesso
    except Exception:
        return False


def chiedi(domanda: str, predefinito: str = "") -> str:
    suffisso = f" [{predefinito}]" if predefinito else ""
    return input(f"{domanda}{suffisso}: ").strip() or predefinito


def leggi_env() -> dict:
    """Legge il .env esistente per non perdere le altre impostazioni."""
    valori = {}
    if os.path.isfile(PERCORSO_ENV):
        with open(PERCORSO_ENV, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if riga and not riga.startswith("#") and "=" in riga:
                    c, _, v = riga.partition("=")
                    valori[c.strip()] = v.strip()
    return valori


def scrivi_env(nuovi: dict) -> None:
    """Aggiorna il .env conservando le impostazioni gia' presenti."""
    valori = leggi_env()
    valori.update(nuovi)
    righe = ["# Configurazione NOC — generato dagli script di configurazione",
             "# NON condividere questo file: contiene codici di accesso.", ""]
    for chiave, valore in valori.items():
        righe.append(f"{chiave}={valore}")
    with open(PERCORSO_ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(righe) + "\n")
    try:
        os.chmod(PERCORSO_ENV, 0o600)
    except OSError:
        pass


def istruzioni_bot() -> None:
    print("""
PRIMA PARTE — creare il bot (si fa una volta sola, dal telefono)

  1. Apri Telegram e cerca:   @BotFather
     (ha la spunta blu di verifica)

  2. Scrivigli:   /newbot

  3. Ti chiede un nome:       SigraFilm NOC
     e poi un nome utente che deve finire per "bot", per esempio:
                              sigrafilm_noc_bot
     (se dice che e' gia' preso, provane un altro)

  4. Ti risponde con un codice lungo, tipo:
        8123456789:AAHk3l-QwErTyUiOpAsDfGhJkLzXcVbNm
     Copialo: serve qui sotto.
""")


def main() -> int:
    print("=== Configurazione notifiche Telegram — SigraFilm NOC ===")

    print("\nControllo che questo PC raggiunga Telegram...")
    if not verifica_rete():
        print("""
ERRORE: api.telegram.org non e' raggiungibile da questo PC.

Telegram usa la porta 443, la stessa del web normale, quindi se il
browser naviga dovrebbe funzionare. Possibili cause:

  1. ANTIVIRUS con filtro del traffico web (Kaspersky, Eset, Avast):
     blocca i programmi diversi dal browser. Cerca una voce tipo
     "Protezione web" o "Controllo traffico" e disattivala per prova.

  2. FIREWALL DI WINDOWS che blocca python.exe:
     Sicurezza di Windows > Firewall > Consenti app.

  3. Filtro sulla rete aziendale che consente solo il browser.

Per verificare: apri https://api.telegram.org nel browser DI QUESTO PC.
Se il browser la apre e questo script no, e' l'antivirus o il firewall.
""")
        return 1
    print("   OK: Telegram raggiungibile.")

    esistente = leggi_env()
    if esistente.get("TELEGRAM_TOKEN"):
        print("\nEsiste gia' una configurazione Telegram.")
        if chiedi("Vuoi rifarla? (s/n)", "n").lower() not in ("s", "si", "sì"):
            print("Annullato: nessuna modifica.")
            return 0

    istruzioni_bot()
    token = chiedi("Incolla qui il codice del bot").strip()
    if not token or ":" not in token:
        print("\nERRORE: il codice non sembra valido.")
        print("Deve essere una cosa tipo  8123456789:AAHk3l-QwErTy...")
        return 1

    # Verifica che il bot esista
    print("\nVerifico il bot...")
    r = api(token, "getMe")
    if not r.get("ok"):
        print(f"ERRORE: {r.get('description', 'codice rifiutato da Telegram')}")
        print("Controlla di aver copiato tutto il codice, senza spazi.")
        return 1
    nome_bot = r["result"].get("username", "?")
    print(f"   Bot trovato: @{nome_bot}")

    # Trova il destinatario
    print(f"""
SECONDA PARTE — dire al bot a chi scrivere

  1. Su Telegram apri la chat con:   @{nome_bot}
  2. Premi AVVIA (oppure scrivi):    /start

  Se vuoi che le notifiche arrivino a piu' persone, crea un gruppo,
  aggiungi @{nome_bot} e scrivi un messaggio qualsiasi nel gruppo.
""")
    input("Fatto? Premi Invio per continuare... ")

    print("\nCerco il destinatario...")
    chat_id, chi = None, ""
    for tentativo in range(3):
        r = api(token, "getUpdates", {"timeout": 0})
        for agg in reversed(r.get("result", [])):
            msg = agg.get("message") or agg.get("channel_post")
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id"))
            chi = (chat.get("title")
                   or " ".join(filter(None, [chat.get("first_name"),
                                             chat.get("last_name")]))
                   or chat.get("username") or "?")
            break
        if chat_id:
            break
        if tentativo < 2:
            print("   Non trovato, riprovo tra 3 secondi...")
            time.sleep(3)

    if not chat_id:
        print("""
ERRORE: nessun messaggio trovato.

Assicurati di aver premuto AVVIA nella chat con il bot (o di aver
scritto qualcosa nel gruppo) e rilancia questo script.
""")
        return 1

    print(f"   Destinatario: {chi}  (id {chat_id})")

    base_url = chiedi("\nIndirizzo web del sito (per i link nelle notifiche)",
                      esistente.get("APP_BASE_URL") or "http://188.8.192.138:5000")

    # Messaggio di prova PRIMA di salvare
    print("\nInvio un messaggio di prova...")
    r = api(token, "sendMessage", {
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "text": ("✅ <b>Notifiche NOC attive</b>\n\n"
                 "Da adesso ricevi un avviso qui ogni volta che un cliente "
                 "apre un ticket o scrive un messaggio."),
    })
    if not r.get("ok"):
        print(f"ERRORE: {r.get('description')}")
        return 1

    print("Messaggio inviato. Controlla Telegram.\n")
    if chiedi("L'hai ricevuto? (s/n)", "s").lower() not in ("s", "si", "sì"):
        print("\nNiente salvato. Verifica e rilancia lo script.")
        return 1

    scrivi_env({
        "TELEGRAM_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
        "APP_BASE_URL": base_url,
    })

    print(f"\nFatto: configurazione salvata in {PERCORSO_ENV}")
    print("Riavvia il sito per attivare le notifiche.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
