"""
Configurazione guidata delle notifiche email.

Da eseguire sul PC dove gira il sito:

    python configura_email.py

Chiede i dati della casella (la password non viene mai mostrata a schermo
né salvata nella cronologia dei comandi), scrive il file .env e invia
subito una mail di prova per verificare che tutto funzioni.
"""
import getpass
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr

PERCORSO_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Impostazioni note dei principali gestori italiani.
# (host, porta, ssl_diretto)
GESTORI = {
    "1": ("Aruba",                    "smtps.aruba.it",     465, True),
    "2": ("Register.it",              "authsmtp.register.it", 465, True),
    "3": ("Google Workspace / Gmail", "smtp.gmail.com",     587, False),
    "4": ("Microsoft 365 / Outlook",  "smtp.office365.com", 587, False),
    "5": ("MCLink",                   "smtp.mclink.it",     465, True),
    "6": ("Altro (inserisco a mano)", None,                 None, None),
}


def chiedi(domanda: str, predefinito: str = "") -> str:
    suffisso = f" [{predefinito}]" if predefinito else ""
    risposta = input(f"{domanda}{suffisso}: ").strip()
    return risposta or predefinito


def scegli_gestore():
    print("Chi gestisce la casella di posta?\n")
    for chiave, (nome, host, porta, _) in GESTORI.items():
        dettaglio = f"  ({host}:{porta})" if host else ""
        print(f"  {chiave}. {nome}{dettaglio}")
    print()

    while True:
        scelta = input("Numero [1]: ").strip() or "1"
        if scelta in GESTORI:
            break
        print("Scelta non valida, riprova.")

    nome, host, porta, ssl_diretto = GESTORI[scelta]
    if host is None:
        host = chiedi("Server SMTP (es. smtp.tuoprovider.it)")
        if not host:
            print("\nERRORE: il server SMTP è obbligatorio.")
            sys.exit(1)
        porta = int(chiedi("Porta", "465") or 465)
        ssl_diretto = porta == 465
    return nome, host, porta, ssl_diretto


def invia_prova(host, porta, ssl_diretto, utente, password, mittente, destinatario):
    msg = EmailMessage()
    msg["Subject"] = "[SigraFilm NOC] Prova invio notifiche"
    msg["From"] = formataddr(("SigraFilm NOC", mittente))
    msg["To"] = destinatario
    msg.set_content(
        "Se stai leggendo questo messaggio, le notifiche del NOC funzionano.\n\n"
        "D'ora in poi riceverai una mail a questo indirizzo ogni volta che un\n"
        "cliente apre un ticket o scrive un messaggio.\n"
    )

    if ssl_diretto:
        with smtplib.SMTP_SSL(host, porta, context=ssl.create_default_context(),
                              timeout=20) as s:
            s.login(utente, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=20) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(utente, password)
            s.send_message(msg)


def main() -> int:
    print("=== Configurazione notifiche email — SigraFilm NOC ===\n")

    if os.path.exists(PERCORSO_ENV):
        print(f"Esiste già un file .env in questa cartella.")
        if chiedi("Vuoi sovrascriverlo? (s/n)", "n").lower() not in ("s", "si", "sì"):
            print("Annullato: nessuna modifica.")
            return 0
        print()

    nome_gestore, host, porta, ssl_diretto = scegli_gestore()
    print(f"\n→ {nome_gestore}: {host}:{porta} ({'SSL' if ssl_diretto else 'STARTTLS'})\n")

    utente = chiedi("Indirizzo della casella", "assistenza@sigrafilm.it")
    password = getpass.getpass("Password della casella (non viene mostrata): ")
    if not password:
        print("\nERRORE: la password è obbligatoria.")
        return 1

    destinatario = chiedi("Dove ricevere le notifiche", utente)
    base_url = chiedi("Indirizzo pubblico del sito", "http://188.8.192.138:5000")

    # Prova l'invio PRIMA di scrivere il file, così non si salva
    # una configurazione che non funziona.
    print("\nInvio una mail di prova...")
    try:
        invia_prova(host, porta, ssl_diretto, utente, password, utente, destinatario)
    except smtplib.SMTPAuthenticationError:
        print("\nERRORE: utente o password rifiutati dal server.")
        print("Se usi Gmail o Microsoft 365 con verifica in due passaggi, serve una")
        print("'password per le app' generata dal pannello del tuo account,")
        print("non la password normale.")
        return 1
    except Exception as e:
        print(f"\nERRORE durante l'invio: {e}")
        print("Controlla server, porta e connessione, poi riprova.")
        return 1

    print(f"Mail di prova inviata a {destinatario}.")
    print("Controlla la casella (guarda anche nello spam) e confermi qui sotto.\n")
    if chiedi("L'hai ricevuta? (s/n)", "s").lower() not in ("s", "si", "sì"):
        print("\nNiente file scritto. Verifica i dati e rilancia lo script.")
        return 1

    contenuto = f"""# Notifiche email — generato da configura_email.py
# NON condividere questo file: contiene la password della casella.

SMTP_HOST={host}
SMTP_PORT={porta}
SMTP_SSL={'1' if ssl_diretto else '0'}
SMTP_USER={utente}
SMTP_PASSWORD={password}
SMTP_FROM={utente}

NOTIFY_EMAIL={destinatario}
APP_BASE_URL={base_url}
"""
    with open(PERCORSO_ENV, "w", encoding="utf-8") as f:
        f.write(contenuto)
    try:
        os.chmod(PERCORSO_ENV, 0o600)   # su Windows viene ignorato
    except OSError:
        pass

    print(f"\nFatto: configurazione salvata in {PERCORSO_ENV}")
    print("Riavvia il sito per attivare le notifiche.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
