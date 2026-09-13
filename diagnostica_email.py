"""
Diagnostica della connessione al server di posta.

Da eseguire sul PC dove gira il sito, quando configura_email.py dà
"timed out" o non riesce a inviare:

    python diagnostica_email.py

Prova le porte SMTP una per una e dice quale funziona, così si capisce
se il blocco è del router, del firewall di Windows o dell'antivirus.
Non serve la password: verifica solo se la connessione si apre.
"""
import socket
import ssl
import smtplib
import sys

HOST_PREDEFINITO = "mail.mclink.it"

# (porta, descrizione, ssl_diretto)
PORTE = [
    (465, "SSL diretto (quella configurata ora)", True),
    (587, "STARTTLS (alternativa più comune)",    False),
    (25,  "SMTP classico (spesso bloccata)",      False),
]

TIMEOUT = 10


def prova_tcp(host: str, porta: int) -> tuple[bool, str]:
    """Verifica se si apre una connessione TCP alla porta."""
    try:
        s = socket.create_connection((host, porta), timeout=TIMEOUT)
        s.close()
        return True, "connessione aperta"
    except socket.timeout:
        return False, "TIMEOUT — nessuna risposta (porta bloccata)"
    except ConnectionRefusedError:
        return False, "RIFIUTATA — il server non ascolta su questa porta"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def prova_smtp(host: str, porta: int, ssl_diretto: bool) -> tuple[bool, str]:
    """Verifica che dall'altra parte risponda davvero un server di posta."""
    try:
        if ssl_diretto:
            with smtplib.SMTP_SSL(host, porta,
                                  context=ssl.create_default_context(),
                                  timeout=TIMEOUT) as s:
                s.ehlo()
                return True, "server di posta OK" + (
                    " (accetta autenticazione)" if s.has_extn("auth") else "")
        else:
            with smtplib.SMTP(host, porta, timeout=TIMEOUT) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                    return True, "server di posta OK con STARTTLS" + (
                        " (accetta autenticazione)" if s.has_extn("auth") else "")
                except smtplib.SMTPNotSupportedError:
                    return True, "server di posta OK ma SENZA cifratura"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    print("=== Diagnostica connessione posta — SigraFilm NOC ===\n")

    host = input(f"Server SMTP [{HOST_PREDEFINITO}]: ").strip() or HOST_PREDEFINITO

    # 1. Il nome del server si risolve?
    print(f"\n1) Risoluzione del nome '{host}'...")
    try:
        ip = socket.gethostbyname(host)
        print(f"   OK: {host} -> {ip}")
    except Exception as e:
        print(f"   ERRORE: {e}")
        print("\n   Il nome del server non si risolve. Controlla di averlo")
        print("   scritto giusto e che il PC abbia la connessione a internet.")
        return 1

    # 2. Internet funziona in generale?
    print("\n2) Connessione a internet...")
    ok_web, _ = prova_tcp("www.google.com", 443)
    print("   OK: il PC naviga" if ok_web else
          "   ERRORE: nessuna connessione a internet")
    if not ok_web:
        return 1

    # 3. Quali porte di posta sono aperte?
    print(f"\n3) Porte di posta su {host}:\n")
    funzionanti = []
    for porta, descrizione, ssl_diretto in PORTE:
        print(f"   Porta {porta} — {descrizione}")
        ok, dettaglio = prova_tcp(host, porta)
        print(f"      TCP : {dettaglio}")
        if ok:
            ok2, dettaglio2 = prova_smtp(host, porta, ssl_diretto)
            print(f"      SMTP: {dettaglio2}")
            if ok2:
                funzionanti.append((porta, ssl_diretto))
        print()

    # 4. Conclusione
    print("=" * 58)
    if funzionanti:
        porta, ssl_diretto = funzionanti[0]
        print(f"\nFUNZIONA la porta {porta}"
              f" ({'SSL diretto' if ssl_diretto else 'STARTTLS'}).\n")
        if porta != 465:
            print("Non e' quella configurata (465). Rilancia configura_email.py,")
            print("scegli '6. Altro' e inserisci:")
            print(f"   Server SMTP : {host}")
            print(f"   Porta       : {porta}")
        else:
            print("La connessione va: se l'invio fallisce ancora, il problema")
            print("e' nelle credenziali, non nella rete.")
        return 0

    print("\nNESSUNA porta di posta raggiungibile.\n")
    print("La connessione a internet funziona, quindi qualcosa blocca")
    print("specificamente la posta in uscita. In ordine di probabilita':\n")
    print("  1. ANTIVIRUS — la 'protezione posta' di Avast, Kaspersky, Norton")
    print("     ed Eset blocca i programmi che inviano email. Cerca una voce")
    print("     tipo 'Scudo posta' o 'Mail shield' e disattivala per prova.\n")
    print("  2. FIREWALL DI WINDOWS — puo' bloccare python.exe. Consenti")
    print("     l'app in: Sicurezza di Windows > Firewall > Consenti app.\n")
    print("  3. ROUTER o PROVIDER — molti bloccano le porte SMTP in uscita")
    print("     per limitare lo spam. Va chiesto a chi gestisce la linea.\n")
    print("Per capire quale dei tre: se dal PC usi gia' un programma di posta")
    print("(Outlook, Thunderbird) e QUELLO invia senza problemi, allora la")
    print("rete e' a posto ed e' l'antivirus che blocca Python.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
