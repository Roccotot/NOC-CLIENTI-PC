"""
Invio notifiche email per nuovi ticket e nuovi messaggi dei clienti.

Le impostazioni si leggono da impostazioni.py, quindi si cambiano dalla
pagina web del portale senza riavviare il sito.

L'invio avviene collegandosi direttamente al server di posta.

Se manca la configurazione le notifiche vengono saltate e il sito continua
a funzionare normalmente.
"""
import os
import ssl
import smtplib
import threading
import traceback
from email.message import EmailMessage
from email.utils import formataddr

import impostazioni

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


def invia_adesso(subject: str, html: str, testo: str, destinatario: str = "") -> None:
    """
    Invio immediato e bloccante, senza catturare gli errori.
    Serve al pulsante "invia prova" della pagina impostazioni, che deve
    poter mostrare il motivo esatto del fallimento.
    """
    imp = impostazioni.tutte()
    destinatario = destinatario or imp.get("notify_email", "")
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


def notifica_richiesta_registrazione(nome: str, email: str, telefono: str,
                                     nome_cinema: str) -> None:
    """
    Avvisa l'assistenza che qualcuno ha chiesto l'accesso dalla pagina di login.

    Senza questa notifica la richiesta resterebbe ferma nella pagina Utenti
    finche' qualcuno non ci passa per caso.
    """
    colore = "#7c3aed"
    base = impostazioni.leggi("app_base_url").rstrip("/")
    link = f"{base}/users" if base else ""

    righe = [
        ("Nome",     _escape(nome)),
        ("Cinema",   _escape(nome_cinema)),
        ("Telefono", _escape(telefono)),
        ("Email",    _escape(email)),
    ]

    corpo = (
        '<p style="margin:20px 0 0;color:#374151;font-size:14px;line-height:1.6;">'
        'La richiesta è in attesa nella pagina Utenti. Per approvarla, premi il '
        'pulsante ✉ sulla sua riga: il portale genera una password e gliela '
        'manda per email. Se non la riconosci, elimina la riga con ✕.</p>'
    )

    # _wrap mette un bottone intitolato "Apri il ticket": qui il link porta
    # alla pagina Utenti, quindi lo si costruisce a mano.
    if link:
        corpo += (f'<p style="margin:24px 0 0;">'
                  f'<a href="{link}" style="display:inline-block;background:{colore};'
                  f'color:#ffffff;text-decoration:none;padding:11px 22px;'
                  f'border-radius:6px;font-size:14px;font-weight:600;">'
                  f'Apri la pagina Utenti</a></p>')

    subject = f"[NOC] Richiesta di accesso — {nome_cinema}"
    html    = _wrap("Nuova richiesta di accesso", colore, righe, corpo, "")

    testo = (
        f"Nuova richiesta di accesso al portale\n\n"
        f"Nome:     {nome}\n"
        f"Cinema:   {nome_cinema}\n"
        f"Telefono: {telefono}\n"
        f"Email:    {email}\n\n"
        f"La richiesta e' in attesa nella pagina Utenti. Per approvarla premi\n"
        f"il pulsante di invio credenziali sulla sua riga.\n"
    )
    if link:
        testo += f"\n{link}\n"

    _send_async(subject, html, testo)


def invia_credenziali(username: str, password: str, email_cliente: str,
                      nomi_cinema: list = None) -> None:
    """
    Manda a un nuovo utente le credenziali e la spiegazione del sito.

    La password va passata in chiaro da chi chiama, perché sul disco è
    salvata solo cifrata e non si può rileggere: chi usa questa funzione
    ne genera una nuova e la comunica qui.
    """
    if not email_cliente:
        raise ValueError("L'utente non ha un indirizzo email: aggiungilo "
                         "con il pulsante ✏ prima di inviare le credenziali.")

    indirizzo = impostazioni.leggi("app_base_url").rstrip("/") or ""
    colore = "#2563eb"

    cinema = ""
    if nomi_cinema:
        voci = "".join(f"<li>{_escape(n)}</li>" for n in nomi_cinema)
        cinema = (f'<p style="margin:18px 0 6px;color:#374151;font-size:14px;">'
                  f'Vedrai le segnalazioni di:</p>'
                  f'<ul style="margin:0;padding-left:20px;color:#111827;'
                  f'font-size:14px;line-height:1.7;">{voci}</ul>')

    bottone = ""
    if indirizzo:
        bottone = (f'<p style="margin:26px 0 0;text-align:center;">'
                   f'<a href="{indirizzo}" style="display:inline-block;'
                   f'background:{colore};color:#ffffff;text-decoration:none;'
                   f'padding:13px 28px;border-radius:6px;font-size:15px;'
                   f'font-weight:600;">Vai al portale</a></p>')

    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f3f4f6;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;
    background:#ffffff;border-radius:10px;overflow:hidden;
    box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <tr><td style="background:{colore};padding:22px 26px;">
      <div style="color:#ffffff;font-size:19px;font-weight:700;">
        Benvenuto nel portale assistenza SigraFilm</div>
    </td></tr>
    <tr><td style="padding:26px;">

      <p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
        Da oggi puoi segnalarci i guasti delle apparecchiature direttamente
        dal portale, invece di telefonare o scrivere una email.
      </p>

      <p style="margin:18px 0 6px;color:#374151;font-size:14px;line-height:1.6;">
        Dal portale puoi:
      </p>
      <ul style="margin:0;padding-left:20px;color:#374151;font-size:14px;line-height:1.8;">
        <li>aprire una segnalazione indicando sala e problema</li>
        <li>allegare foto o video del guasto</li>
        <li>scambiare messaggi con noi sulla singola segnalazione</li>
        <li>seguire lo stato dell'intervento fino alla chiusura</li>
      </ul>
      {cinema}

      <div style="margin-top:24px;padding:16px 18px;background:#f9fafb;
        border-left:3px solid {colore};border-radius:0 6px 6px 0;">
        <div style="color:#6b7280;font-size:11px;text-transform:uppercase;
          letter-spacing:.5px;margin-bottom:10px;">I tuoi dati di accesso</div>
        <table cellpadding="0" cellspacing="0">
          <tr><td style="padding:3px 14px 3px 0;color:#6b7280;font-size:13px;">Indirizzo</td>
              <td style="padding:3px 0;color:#111827;font-size:14px;font-weight:600;">
                {_escape(indirizzo) or "(chiedi a noi)"}</td></tr>
          <tr><td style="padding:3px 14px 3px 0;color:#6b7280;font-size:13px;">Utente</td>
              <td style="padding:3px 0;color:#111827;font-size:15px;font-weight:700;
                font-family:monospace;">{_escape(username)}</td></tr>
          <tr><td style="padding:3px 14px 3px 0;color:#6b7280;font-size:13px;">Password</td>
              <td style="padding:3px 0;color:#111827;font-size:15px;font-weight:700;
                font-family:monospace;">{_escape(password)}</td></tr>
        </table>
      </div>

      {bottone}

      <p style="margin:26px 0 0;color:#6b7280;font-size:12px;line-height:1.6;
        border-top:1px solid #e5e7eb;padding-top:16px;">
        Conserva questa email o salva la password: per motivi di sicurezza
        non possiamo rileggerla, possiamo solo generarne una nuova.
        Per qualsiasi difficolt&agrave; scrivici, siamo a disposizione.
      </p>

    </td></tr>
    <tr><td style="padding:14px 26px;background:#f9fafb;
      border-top:1px solid #e5e7eb;color:#9ca3af;font-size:11px;">
      SigraFilm S.a.s. — Assistenza tecnica cinematografica
    </td></tr>
  </table>
</body></html>"""

    elenco = ("\nVedrai le segnalazioni di:\n"
              + "".join(f"  - {n}\n" for n in nomi_cinema)) if nomi_cinema else ""

    testo = f"""Benvenuto nel portale assistenza SigraFilm

Da oggi puoi segnalarci i guasti delle apparecchiature direttamente dal
portale, invece di telefonare o scrivere una email.

Dal portale puoi:
  - aprire una segnalazione indicando sala e problema
  - allegare foto o video del guasto
  - scambiare messaggi con noi sulla singola segnalazione
  - seguire lo stato dell'intervento fino alla chiusura
{elenco}
I TUOI DATI DI ACCESSO

  Indirizzo: {indirizzo or "(chiedi a noi)"}
  Utente:    {username}
  Password:  {password}

Conserva questa email o salva la password: per motivi di sicurezza non
possiamo rileggerla, possiamo solo generarne una nuova.

Per qualsiasi difficolta' scrivici, siamo a disposizione.

SigraFilm S.a.s. — Assistenza tecnica cinematografica
"""

    _send_async("Le tue credenziali per il portale assistenza SigraFilm",
                html, testo, destinatario=email_cliente)


def notifica_cambio_stato(problem, email_cliente: str,
                          vecchio_stato: str, vecchia_urgenza: str) -> None:
    """
    Avvisa il cliente che il suo ticket è stato aggiornato.

    Serve perché altrimenti il cliente non ha modo di sapere che qualcuno
    ha preso in carico il problema o lo ha chiuso: doveva ricontrollare
    il sito a mano.
    """
    if not email_cliente:
        return

    cambiato_stato   = problem.stato != vecchio_stato
    cambiata_urgenza = problem.urgenza != vecchia_urgenza
    if not (cambiato_stato or cambiata_urgenza):
        return

    colori = {"Chiuso": "#16a34a", "In corso": "#2563eb"}
    colore = colori.get(problem.stato, "#6b7280")
    link   = _ticket_url(problem.id)

    righe = [
        ("Ticket", f"#{problem.id}"),
        ("Cinema", problem.cinema),
        ("Sala",   str(problem.sala)),
    ]
    if cambiato_stato:
        righe.append(("Stato", f"{vecchio_stato} → <b>{_escape(problem.stato)}</b>"))
    else:
        righe.append(("Stato", problem.stato))
    if cambiata_urgenza:
        righe.append(("Urgenza", f"{vecchia_urgenza} → <b>{_escape(problem.urgenza)}</b>"))

    if problem.stato == "Chiuso":
        titolo = f"Ticket #{problem.id} chiuso"
        frase  = ("Il problema risulta risolto e il ticket è stato chiuso. "
                  "Se dovesse ripresentarsi, aprine pure uno nuovo.")
    elif problem.stato == "In corso":
        titolo = f"Ticket #{problem.id} preso in carico"
        frase  = "Ci stiamo lavorando. Ti aggiorniamo appena ci sono novità."
    else:
        titolo = f"Ticket #{problem.id} aggiornato"
        frase  = "Lo stato del tuo ticket è cambiato."

    corpo = (f'<p style="margin:20px 0 0;color:#374151;font-size:14px;'
             f'line-height:1.5;">{frase}</p>')

    subject = f"[SigraFilm] {titolo} — {problem.cinema}"
    html    = _wrap(titolo, colore, righe, corpo, link)

    testo = (
        f"{titolo}\n\n"
        f"Cinema: {problem.cinema}\n"
        f"Sala:   {problem.sala}\n"
        f"Stato:  {vecchio_stato} -> {problem.stato}\n"
    )
    if cambiata_urgenza:
        testo += f"Urgenza: {vecchia_urgenza} -> {problem.urgenza}\n"
    testo += f"\n{frase}\n"
    if link:
        testo += f"\n{link}\n"

    _send_async(subject, html, testo, destinatario=email_cliente)


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
