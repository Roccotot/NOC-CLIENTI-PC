"""
Invio notifiche email per nuovi ticket e nuovi messaggi dei clienti.

Configurazione tramite variabili d'ambiente (file .env o variabili di sistema):

    SMTP_HOST       server SMTP          (es. smtps.aruba.it)
    SMTP_PORT       porta                (default 587)
    SMTP_USER       utente / indirizzo   (es. assistenza@sigrafilm.it)
    SMTP_PASSWORD   password casella
    SMTP_FROM       mittente visualizzato (default = SMTP_USER)
    SMTP_SSL        "1" per SSL diretto porta 465, altrimenti STARTTLS
    NOTIFY_EMAIL    destinatario notifiche (default assistenza@sigrafilm.it)
    APP_BASE_URL    url pubblico del sito, per i link nelle email

Se SMTP_HOST o SMTP_USER non sono configurati le notifiche vengono
silenziosamente saltate: il sito continua a funzionare normalmente.
"""
import os
import ssl
import smtplib
import threading
import traceback
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST     = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM     = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER
SMTP_SSL      = os.environ.get("SMTP_SSL", "").strip() in ("1", "true", "yes")
NOTIFY_EMAIL  = os.environ.get("NOTIFY_EMAIL", "assistenza@sigrafilm.it").strip()
APP_BASE_URL  = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")

FROM_NAME = "SigraFilm NOC"


def is_configured() -> bool:
    """True se ci sono abbastanza dati per tentare l'invio."""
    return bool(SMTP_HOST and SMTP_USER and NOTIFY_EMAIL)


def _send(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """Invio effettivo (bloccante). Chiamato dentro un thread."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = formataddr((FROM_NAME, SMTP_FROM))
    msg["To"]      = destinatario or NOTIFY_EMAIL
    msg.set_content(testo)
    msg.add_alternative(html, subtype="html")

    try:
        if SMTP_SSL:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass  # server senza TLS: procedi comunque
                if SMTP_PASSWORD:
                    s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        print(f"[mail] Notifica inviata a {NOTIFY_EMAIL}: {subject}")
    except Exception:
        # Non deve mai bloccare il sito
        print("[mail] ERRORE invio notifica:")
        traceback.print_exc()


def _send_async(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """Invia in background senza bloccare la risposta HTTP."""
    if not is_configured():
        print("[mail] SMTP non configurato — notifica saltata.")
        return
    if destinatario and "@" not in destinatario:
        print(f"[mail] Destinatario non valido, notifica saltata: {destinatario!r}")
        return
    threading.Thread(
        target=_send, args=(subject, html, testo, destinatario), daemon=True
    ).start()


def _ticket_url(problem_id: int) -> str:
    if APP_BASE_URL:
        return f"{APP_BASE_URL}/problems/{problem_id}"
    return ""


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
