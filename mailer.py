"""
Invio notifiche email per nuovi ticket e nuovi messaggi dei clienti.

Le impostazioni si leggono da impostazioni.py, quindi si cambiano dalla
pagina web del portale senza riavviare il sito.

Tre modi di invio:

  "smtp" — collegamento diretto al server di posta (porta 465/587).
           E' il modo classico, ma molte reti bloccano quelle porte.

  "blat" — stessa cosa ma affidata a blat.exe, il programma da riga di
           comando per Windows. Utile quando l'antivirus blocca python.exe
           ma lascia passare altri eseguibili, oppure quando funziona la
           porta 25 e non la 465.

  "web"  — invio tramite il servizio Brevo, che espone un'interfaccia web
           sulla porta 443: funziona anche dove l'SMTP e' bloccato.

Se manca la configurazione le notifiche vengono saltate e il sito continua
a funzionare normalmente.
"""
import json
import os
import ssl
import smtplib
import threading
import traceback
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

import impostazioni

URL_BREVO = "https://api.brevo.com/v3/smtp/email"
TIMEOUT = 20

FROM_NAME = "SigraFilm NOC"


def is_configured() -> bool:
    """True se c'è abbastanza configurazione per tentare l'invio."""
    return impostazioni.configurato()


def _mittente(imp: dict) -> str:
    return imp.get("smtp_from") or imp.get("smtp_user") or ""


def _invia_smtp(imp, subject, html, testo, destinatario):
    """Invio classico, collegandosi al server di posta."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = formataddr((FROM_NAME, _mittente(imp)))
    msg["To"]      = destinatario
    msg.set_content(testo)
    msg.add_alternative(html, subtype="html")

    host = imp["smtp_host"]
    porta = int(imp.get("smtp_port") or 465)
    utente = imp.get("smtp_user", "")
    password = imp.get("smtp_password", "")

    if str(imp.get("smtp_ssl", "")).strip() in ("1", "true", "yes"):
        with smtplib.SMTP_SSL(host, porta, context=ssl.create_default_context(),
                              timeout=TIMEOUT) as s:
            if password:
                s.login(utente, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=TIMEOUT) as s:
            s.ehlo()
            try:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            if password:
                s.login(utente, password)
            s.send_message(msg)


def _invia_web(imp, subject, html, testo, destinatario):
    """Invio tramite Brevo: usa la porta 443, quindi passa dove l'SMTP no."""
    payload = {
        "sender": {"email": _mittente(imp), "name": FROM_NAME},
        "to": [{"email": destinatario}],
        "subject": subject,
        "htmlContent": html,
        "textContent": testo,
    }
    richiesta = urllib.request.Request(
        URL_BREVO,
        data=json.dumps(payload).encode(),
        headers={"api-key": imp.get("api_key", ""),
                 "content-type": "application/json",
                 "accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as r:
            r.read()
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Brevo ha rifiutato l'invio (HTTP {e.code}): {dettaglio}")


def _invia_blat(imp, subject, html, testo, destinatario):
    """
    Invio tramite blat.exe, il programma da riga di comando per Windows.

    Parla comunque SMTP: non aggira il fatto che serva una porta aperta.
    Ha senso in due casi:
      - il server accetta la porta 25 mentre la 465 e' bloccata;
      - l'antivirus blocca python.exe ma lascia passare blat.exe, cosa
        frequente con le "protezioni posta" di Avast, Kaspersky ed Eset.

    Il corpo viene scritto su un file temporaneo invece che passato come
    argomento: l'HTML e' lungo e conterrebbe caratteri che la riga di
    comando di Windows interpreta male.
    """
    import subprocess
    import tempfile

    percorso_blat = (imp.get("blat_path") or "blat.exe").strip()
    host = imp.get("smtp_host", "").strip()
    porta = (imp.get("smtp_port") or "25").strip()

    fd, file_corpo = tempfile.mkstemp(suffix=".html", prefix="noc_mail_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)

        comando = [
            percorso_blat,
            "-to", destinatario,
            "-f", _mittente(imp),
            "-subject", subject,
            "-bodyF", file_corpo,
            "-html",
            "-charset", "UTF-8",
            "-server", f"{host}:{porta}",
        ]
        if imp.get("smtp_user"):
            comando += ["-u", imp["smtp_user"]]
        if imp.get("smtp_password"):
            comando += ["-pw", imp["smtp_password"]]

        try:
            esito = subprocess.run(comando, capture_output=True, text=True,
                                   timeout=TIMEOUT + 20)
        except FileNotFoundError:
            raise RuntimeError(
                f"blat non trovato in «{percorso_blat}». Indica il percorso "
                f"completo, per esempio C:\\blat\\blat.exe")
        except subprocess.TimeoutExpired:
            raise RuntimeError("blat non ha risposto entro il tempo massimo: "
                               "molto probabilmente la porta e' bloccata.")

        if esito.returncode != 0:
            # Mostra tutto quello che blat ha detto: senza il suo output
            # non c'e' modo di capire se il problema e' la porta, le
            # credenziali o la cifratura richiesta dal server.
            uscita = "\n".join(p for p in (esito.stdout, esito.stderr) if p and p.strip())
            uscita = uscita.strip() or "(blat non ha scritto nulla)"

            # Il comando eseguito, con la password oscurata
            mostrato = list(comando)
            if "-pw" in mostrato:
                mostrato[mostrato.index("-pw") + 1] = "********"
            riga_comando = " ".join(mostrato)

            raise RuntimeError(
                f"blat ha restituito errore (codice {esito.returncode}).\n\n"
                f"Risposta di blat:\n{uscita[:900]}\n\n"
                f"Comando eseguito:\n{riga_comando}")
    finally:
        try:
            os.remove(file_corpo)
        except OSError:
            pass


def invia_adesso(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """
    Invio immediato e bloccante, senza catturare gli errori.
    Serve al pulsante "invia prova" della pagina impostazioni, che deve
    poter mostrare il motivo esatto del fallimento.
    """
    imp = impostazioni.tutte()
    destinatario = destinatario or imp.get("notify_email", "")
    metodo = imp.get("metodo_invio")
    if metodo == "web":
        _invia_web(imp, subject, html, testo, destinatario)
    elif metodo == "blat":
        _invia_blat(imp, subject, html, testo, destinatario)
    else:
        _invia_smtp(imp, subject, html, testo, destinatario)


def _send(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """Invio in background: non deve mai far cadere il sito."""
    try:
        invia_adesso(subject, html, testo, destinatario)
        print(f"[mail] Notifica inviata a {destinatario or '(predefinito)'}")
    except Exception:
        print("[mail] ERRORE invio notifica:")
        traceback.print_exc()


def _send_async(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """Invia in background senza bloccare la risposta HTTP."""
    if not is_configured():
        print("[mail] Notifiche email non configurate — saltata.")
        return
    destinatario = destinatario or impostazioni.leggi("notify_email")
    if destinatario and "@" not in destinatario:
        print(f"[mail] Destinatario non valido, notifica saltata: {destinatario!r}")
        return
    threading.Thread(
        target=_send, args=(subject, html, testo, destinatario), daemon=True
    ).start()


def _ticket_url(problem_id: int) -> str:
    base = impostazioni.leggi("app_base_url").rstrip("/")
    return f"{base}/problems/{problem_id}" if base else ""


def _wrap(titolo: str, colore: str, righe: list[tuple[str, str]],
          corpo: str, link: str) -> str:
    """Costruisce l'HTML della mail."""
    righe_html = "".join(
        f'<tr>'
        f'<td style="padding:5px 14px 5px 0;color:#6b7280;font-size:13px;'
        f'white-space:nowrap;vertical-align:top;">{k}</td>'
        f'<td style="padding:5px 0;color:#111827;font-size:14px;'
        f'font-weight:600;">{v}</td>'
        f'</tr>'
        for k, v in righe if v
    )

    bottone = ""
    if link:
        bottone = (
            f'<p style="margin:26px 0 0;">'
            f'<a href="{link}" style="display:inline-block;background:{colore};'
            f'color:#ffffff;text-decoration:none;padding:11px 22px;'
            f'border-radius:6px;font-size:14px;font-weight:600;">'
            f'Apri il ticket</a></p>'
        )

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f3f4f6;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;
    background:#ffffff;border-radius:10px;overflow:hidden;
    box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr><td style="background:{colore};padding:18px 26px;">
      <div style="color:#ffffff;font-size:17px;font-weight:700;">{titolo}</div>
    </td></tr>
    <tr><td style="padding:24px 26px;">
      <table cellpadding="0" cellspacing="0">{righe_html}</table>
      {corpo}
      {bottone}
    </td></tr>
    <tr><td style="padding:14px 26px;background:#f9fafb;
      border-top:1px solid #e5e7eb;color:#9ca3af;font-size:11px;">
      Notifica automatica — SigraFilm NOC
    </td></tr>
  </table>
</body></html>"""


def notifica_nuovo_ticket(problem) -> None:
    """Invia la notifica per un nuovo ticket aperto da un cliente."""
    colori = {"Critico": "#dc2626", "Urgente": "#d97706"}
    colore = colori.get(problem.urgenza, "#2563eb")
    link   = _ticket_url(problem.id)

    righe = [
        ("Cinema",   problem.cinema),
        ("Città",    problem.città),
        ("Sala",     str(problem.sala)),
        ("Urgenza",  problem.urgenza),
        ("Aperto da", problem.autore),
    ]

    corpo = (
        f'<div style="margin-top:20px;padding:14px 16px;background:#f9fafb;'
        f'border-left:3px solid {colore};border-radius:0 6px 6px 0;">'
        f'<div style="color:#6b7280;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px;">Descrizione</div>'
        f'<div style="color:#111827;font-size:14px;line-height:1.5;'
        f'white-space:pre-wrap;">{_escape(problem.tipo)}</div></div>'
    )

    subject = f"[NOC] Nuovo ticket #{problem.id} — {problem.cinema} ({problem.urgenza})"
    html    = _wrap(f"Nuovo ticket #{problem.id}", colore, righe, corpo, link)

    testo = (
        f"Nuovo ticket #{problem.id}\n\n"
        f"Cinema:   {problem.cinema}\n"
        f"Città:    {problem.città}\n"
        f"Sala:     {problem.sala}\n"
        f"Urgenza:  {problem.urgenza}\n"
        f"Autore:   {problem.autore}\n\n"
        f"Descrizione:\n{problem.tipo}\n"
    )
    if link:
        testo += f"\nApri: {link}\n"

    _send_async(subject, html, testo)


def notifica_nuovo_messaggio(problem, autore: str, testo_msg: str) -> None:
    """Invia la notifica per un nuovo messaggio scritto da un cliente."""
    colore = "#2563eb"
    link   = _ticket_url(problem.id)

    righe = [
        ("Ticket",  f"#{problem.id}"),
        ("Cinema",  problem.cinema),
        ("Sala",    str(problem.sala)),
        ("Da",      autore),
    ]

    corpo = (
        f'<div style="margin-top:20px;padding:14px 16px;background:#eff6ff;'
        f'border-left:3px solid {colore};border-radius:0 6px 6px 0;">'
        f'<div style="color:#6b7280;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px;">Messaggio</div>'
        f'<div style="color:#111827;font-size:14px;line-height:1.5;'
        f'white-space:pre-wrap;">{_escape(testo_msg)}</div></div>'
    )

    subject = f"[NOC] Nuovo messaggio su ticket #{problem.id} — {problem.cinema}"
    html    = _wrap("Nuovo messaggio", colore, righe, corpo, link)

    testo = (
        f"Nuovo messaggio sul ticket #{problem.id}\n\n"
        f"Cinema: {problem.cinema}\n"
        f"Sala:   {problem.sala}\n"
        f"Da:     {autore}\n\n"
        f"Messaggio:\n{testo_msg}\n"
    )
    if link:
        testo += f"\nApri: {link}\n"

    _send_async(subject, html, testo)


def notifica_risposta_al_cliente(problem, email_cliente: str, testo_msg: str) -> None:
    """
    Avvisa il cliente che l'assistenza ha risposto sul suo ticket.

    Senza questa notifica il cliente doveva ricontrollare il sito a mano per
    sapere se qualcuno gli aveva risposto.
    """
    if not email_cliente:
        return

    colore = "#2563eb"
    link   = _ticket_url(problem.id)

    righe = [
        ("Ticket",  f"#{problem.id}"),
        ("Cinema",  problem.cinema),
        ("Sala",    str(problem.sala)),
        ("Stato",   problem.stato),
    ]

    corpo = (
        f'<div style="margin-top:20px;padding:14px 16px;background:#eff6ff;'
        f'border-left:3px solid {colore};border-radius:0 6px 6px 0;">'
        f'<div style="color:#6b7280;font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px;">Risposta dell\'assistenza</div>'
        f'<div style="color:#111827;font-size:14px;line-height:1.5;'
        f'white-space:pre-wrap;">{_escape(testo_msg)}</div></div>'
        f'<p style="margin:18px 0 0;color:#6b7280;font-size:13px;">'
        f'Per rispondere, apri il ticket dal sito.</p>'
    )

    subject = f"[SigraFilm] Risposta al tuo ticket #{problem.id} — {problem.cinema}"
    html    = _wrap("Ti abbiamo risposto", colore, righe, corpo, link)

    testo = (
        f"Abbiamo risposto al tuo ticket #{problem.id}\n\n"
        f"Cinema: {problem.cinema}\n"
        f"Sala:   {problem.sala}\n"
        f"Stato:  {problem.stato}\n\n"
        f"Risposta dell'assistenza:\n{testo_msg}\n\n"
        f"Per rispondere, apri il ticket dal sito.\n"
    )
    if link:
        testo += f"\n{link}\n"

    _send_async(subject, html, testo, destinatario=email_cliente)


def _escape(s: str) -> str:
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
