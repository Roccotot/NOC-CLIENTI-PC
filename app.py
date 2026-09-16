from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
import os
import io
import re
import secrets
import unicodedata
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment


from config import carica_env

carica_env()

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    _reportlab_ok = True
except ImportError:
    _reportlab_ok = False

from storage import store
import mailer
import impostazioni

def _chiave_segreta() -> str:
    """
    Chiave usata per firmare i cookie di sessione.

    Ordine: variabile d'ambiente SECRET_KEY -> file .secret_key -> generata.
    Una chiave prevedibile permetterebbe di falsificare i cookie ed entrare
    come amministratore, quindi non esiste più un valore di default.
    La chiave viene salvata su file così le sessioni sopravvivono ai riavvii.
    """
    chiave = os.environ.get("SECRET_KEY", "").strip()
    if chiave:
        return chiave

    percorso = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
    if os.path.isfile(percorso):
        try:
            with open(percorso, encoding="utf-8") as f:
                chiave = f.read().strip()
            if chiave:
                return chiave
        except Exception as e:
            print(f"[chiave] Impossibile leggere .secret_key: {e}")

    chiave = secrets.token_hex(32)
    try:
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(chiave)
        try:
            os.chmod(percorso, 0o600)  # su Windows viene ignorato
        except OSError:
            pass
        print("[chiave] Generata una nuova SECRET_KEY in .secret_key")
    except Exception as e:
        print(f"[chiave] ATTENZIONE: chiave solo in memoria, i login "
              f"si perderanno a ogni riavvio ({e})")
    return chiave


# --- CONFIGURAZIONE ---
app = Flask(__name__)
app.secret_key = _chiave_segreta()

# Cookie di sessione più difficili da rubare
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # non leggibile da JavaScript
    SESSION_COOKIE_SAMESITE="Lax",  # non inviato da siti terzi
    # Attivare solo quando il sito sarà servito in HTTPS, altrimenti il
    # cookie non viene inviato e il login smette di funzionare.
    SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ATTIVO", "").strip() in ("1", "true", "yes"),
)
ALLEGATI_FOLDER = os.path.join(os.path.dirname(__file__), "allegati")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "bmp", "webp",
                      "doc", "docx", "xls", "xlsx", "txt", "zip", "mp4", "mov", "avi"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
os.makedirs(ALLEGATI_FOLDER, exist_ok=True)

def _cinema_utente() -> list[str]:
    """
    Nomi dei cinema assegnati all'utente collegato.

    Serve a far vedere a chi lavora nello stesso cinema gli stessi ticket:
    prima la visibilità era solo per autore, quindi due account dello stesso
    cinema non vedevano i ticket l'uno dell'altro.
    """
    if session.get("role") == "admin":
        return []          # l'admin vede tutto, nessun filtro
    ids = store.get_cinema_ids_for_user(session.get("user_id"))
    if not ids:
        return []
    return [c.nome for c in store.get_cinemas_by_ids(ids)]


def _puo_vedere(p) -> bool:
    """True se l'utente collegato può vedere/modificare il ticket `p`."""
    if session.get("role") == "admin":
        return True
    if session.get("username") == p.autore:
        return True
    suoi = {n.strip().lower() for n in _cinema_utente()}
    return bool(suoi) and (p.cinema or "").strip().lower() in suoi


def _cinema_folder(cinema_nome: str) -> str:
    """Sanitizza il nome cinema per usarlo come cartella."""
    safe = re.sub(r'[<>:"/\\|?*]', '_', cinema_nome).strip()
    return safe or "sconosciuto"

def _get_allegati(cinema_nome: str, ticket_id: int) -> list[dict]:
    folder = os.path.join(ALLEGATI_FOLDER, _cinema_folder(cinema_nome))
    if not os.path.isdir(folder):
        return []
    prefix = f"{ticket_id}_"
    files = []
    for fname in sorted(os.listdir(folder)):
        if fname.startswith(prefix):
            original = fname[len(prefix):]
            files.append({"filename": fname, "original": original,
                          "cinema_folder": _cinema_folder(cinema_nome)})
    return files

# ── PROTEZIONE CSRF ────────────────────────────────────────────
# Senza questa protezione, una pagina malevola aperta da un utente già
# loggato può inviare form al sito a sua insaputa (cancellare ticket,
# eliminare utenti...). Ogni form include un gettone segreto legato alla
# sessione: le richieste che non lo portano vengono rifiutate.

def _gettone_csrf() -> str:
    """Gettone della sessione corrente, creato al primo utilizzo."""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


@app.context_processor
def _inietta_csrf():
    """Rende disponibile csrf_token() in tutti i template."""
    return {"csrf_token": _gettone_csrf}


@app.before_request
def _verifica_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    atteso = session.get("_csrf")
    inviato = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
    if not atteso or not secrets.compare_digest(str(atteso), str(inviato)):
        app.logger.warning("Richiesta rifiutata per gettone CSRF mancante o errato: %s",
                           request.path)
        abort(400, description="Sessione scaduta o richiesta non valida. "
                               "Ricarica la pagina e riprova.")
    return None


@app.errorhandler(400)
def _errore_400(e):
    """Messaggio comprensibile al posto della pagina di errore grezza."""
    if "user_id" in session:
        flash("Sessione scaduta o richiesta non valida. Riprova.", "warning")
        return redirect(url_for("dashboard"))
    flash("Sessione scaduta. Accedi di nuovo.", "warning")
    return redirect(url_for("login"))


# Inizializza file Excel e dati di default
store.seed()
print("📂 DATABASE: file Excel in cartella data/")


# --- ROUTES ---
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


def _email_assistenza() -> str:
    """Casella a cui far scrivere chi non ha ancora le credenziali."""
    return impostazioni.leggi("notify_email") or "assistenza@sigrafilm.it"


# --- LOGIN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        u = store.get_user_by_username(username)
        if u and u.stato == "richiesta":
            # Si e' registrato da solo ma nessuno gli ha ancora mandato la
            # password: senza questo messaggio proverebbe all'infinito.
            flash("La tua richiesta è in attesa: ti manderemo le credenziali "
                  "per email appena l'avremo approvata.", "info")
            return render_template("login.html",
                                   email_assistenza=_email_assistenza())
        if u and check_password_hash(u.password_hash, password):
            session["user_id"] = u.id
            session["role"] = u.role
            session["username"] = u.username
            flash("Login effettuato", "success")
            return redirect(url_for("dashboard"))
        flash("Credenziali non valide", "danger")
    return render_template("login.html", email_assistenza=_email_assistenza())


# --- REGISTRAZIONE LIBERA ---
# Massimo numero di richieste in attesa contemporaneamente: senza un tetto
# la pagina, che è aperta a chiunque, si potrebbe riempire di iscrizioni
# finte. Quando si raggiunge, basta evadere quelle in coda.
MAX_RICHIESTE_IN_ATTESA = 30


def _email_valida(indirizzo: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", indirizzo))


def _nome_utente_da(nome: str) -> str:
    """
    Trasforma "Mario Rossi" in "mario.rossi".

    Al login il nome utente si digita spesso dal telefono: senza spazi,
    senza accenti e tutto minuscolo si sbaglia molto piu' difficilmente.
    Se il nome scelto e' gia' preso si aggiunge un numero in fondo.
    """
    # Accenti via: à->a, è->e, ç->c... senza dipendere da librerie esterne
    pulito = unicodedata.normalize("NFKD", nome)
    pulito = "".join(c for c in pulito if not unicodedata.combining(c))
    pulito = pulito.lower()
    pulito = re.sub(r"[\s_]+", ".", pulito.strip())
    pulito = re.sub(r"[^a-z0-9.\-]", "", pulito)
    pulito = re.sub(r"\.{2,}", ".", pulito).strip(".-")

    # Nome scritto tutto in un alfabeto che qui non resta (cirillico, cinese…)
    if not pulito:
        pulito = "utente"

    base = pulito[:40]
    candidato = base
    contatore = 1
    while store.get_user_by_username(candidato):
        contatore += 1
        candidato = f"{base}{contatore}"
    return candidato


@app.route("/registrati", methods=["GET", "POST"])
def registrati():
    """
    Il responsabile di un cinema chiede l'accesso da solo.

    Non crea un utente utilizzabile: crea una richiesta che compare nella
    pagina Utenti. La password la genera e la manda l'amministratore con
    il pulsante ✉, così nessuno entra senza essere stato approvato.
    """
    cinemas = store.get_all_cinemas(order_by="città_nome")

    if request.method == "POST":
        nome     = request.form.get("nome", "").strip()
        telefono = request.form.get("telefono", "").strip()
        email    = request.form.get("email", "").strip()
        cinema_id = request.form.get("cinema_id", "").strip()

        dati = {"nome": nome, "telefono": telefono, "email": email,
                "cinema_id": cinema_id}

        def _rifiuta(messaggio, categoria="danger"):
            flash(messaggio, categoria)
            return render_template("registrati.html", cinemas=cinemas, dati=dati)

        if len(nome) < 3:
            return _rifiuta("Scrivi il tuo nome (almeno 3 caratteri).")
        if len(nome) > 60:
            return _rifiuta("Il nome è troppo lungo.")
        if not _email_valida(email):
            return _rifiuta("L'indirizzo email non sembra valido: "
                            "serve per mandarti la password.")
        if len(telefono) < 6:
            return _rifiuta("Lascia un numero di telefono per poterti "
                            "contattare in caso di urgenze.")
        if not cinema_id.isdigit() or not store.get_cinema_by_id(int(cinema_id)):
            return _rifiuta("Scegli il cinema che devi gestire.")

        # Due richieste per la stessa persona sarebbero solo lavoro doppio.
        # Il confronto e' sul nome per esteso e sullo username che ne esce,
        # così si intercetta anche chi era stato creato a mano.
        gia_presente = any(
            (u.nome and u.nome.strip().lower() == nome.lower())
            for u in store.get_all_users()
        ) or bool(store.get_user_by_username(nome))
        if gia_presente:
            return _rifiuta("Esiste già un accesso con questo nome. Se è il "
                            "tuo e hai perso la password, scrivici.", "warning")

        if len(store.utenti_in_attesa()) >= MAX_RICHIESTE_IN_ATTESA:
            return _rifiuta("Al momento non possiamo accettare altre richieste. "
                            "Riprova più tardi o scrivici direttamente.", "warning")

        cinema = store.get_cinema_by_id(int(cinema_id))
        username = _nome_utente_da(nome)

        # Password casuale mai comunicata a nessuno: serve solo a non lasciare
        # la riga senza hash. Quella vera la genera l'amministratore.
        nuovo = store.create_user(
            username=username,
            password_hash=generate_password_hash(secrets.token_urlsafe(32)),
            password_plain="",
            role="user", telefono=telefono, email=email,
            stato="richiesta", nome=nome,
        )
        store.set_user_cinemas(nuovo.id, [cinema.id])

        try:
            mailer.notifica_richiesta_registrazione(nome, username, email,
                                                    telefono, cinema.nome)
        except Exception as e:
            app.logger.warning("Notifica registrazione non inviata: %s", e)

        flash("Richiesta inviata. Ti manderemo le credenziali per email "
              "appena l'avremo controllata.", "success")
        return redirect(url_for("login"))

    return render_template("registrati.html", cinemas=cinemas, dati={})


# NOTA: la vecchia route "/reset-admin-password-7x9k" è stata rimossa.
# Permetteva a CHIUNQUE, senza autenticazione, di reimpostare la password
# admin a un valore noto e prendere il controllo del sito.
# Per un reset d'emergenza usare da riga di comando sul PC del server:
#     python reset_admin.py


# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    flash("Logout effettuato", "info")
    return redirect(url_for("login"))


# --- DASHBOARD ---
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    filter_urgenza = request.args.get("filter_urgenza", "")
    filter_stato   = request.args.get("filter_stato", "")
    ricerca        = request.args.get("q", "").strip()
    uid = session["user_id"]

    e_admin     = session["role"] == "admin"
    mio_autore  = None if e_admin else session["username"]
    miei_cinema = None if e_admin else _cinema_utente()

    problems = store.get_problems_filtered(
        stato_ne="Chiuso",
        autore=mio_autore,
        cinemas=miei_cinema,
        urgenza=filter_urgenza or None,
        stato_eq=filter_stato or None,
        ricerca=ricerca or None,
    )

    all_open = store.get_problems_filtered(
        stato_ne="Chiuso",
        autore=mio_autore,
        cinemas=miei_cinema,
    )
    stats = {
        "total":    len(all_open),
        "aperto":   sum(1 for p in all_open if p.stato == "Aperto"),
        "in_corso": sum(1 for p in all_open if p.stato == "In corso"),
        "chiuso":   0,
        "critico":  sum(1 for p in all_open if p.urgenza == "Critico"),
    }

    if session["role"] == "admin":
        cinemas = store.get_all_cinemas()
    else:
        assigned_ids = store.get_cinema_ids_for_user(uid)
        cinemas = store.get_cinemas_by_ids(assigned_ids) if assigned_ids else store.get_all_cinemas()
    cinemas.sort(key=lambda c: c.nome)
    single_cinema = cinemas[0] if len(cinemas) == 1 else None

    # Contatori messaggi non letti.
    # I commenti si leggono UNA volta sola e si raggruppano: prima si
    # rileggeva l'intero file per ogni ticket in elenco.
    reads = store.get_reads_by_user(uid)
    commenti_per_ticket = store.get_comments_grouped()
    chat_info = {}
    for p in problems:
        comments = commenti_per_ticket.get(p.id, [])
        total = len(comments)
        last_read = reads.get(p.id)
        if last_read is None:
            unread = total
        else:
            unread = sum(1 for c in comments if c.data_ora and c.data_ora > last_read)
        chat_info[p.id] = {"total": total, "unread": unread}

    # Ticket mai aperti dall'utente corrente (evidenziati come "Nuovo")
    new_ticket_ids = {p.id for p in problems if p.id not in reads}

    return render_template(
        "dashboard.html",
        problems=problems,
        filter_urgenza=filter_urgenza,
        ricerca=ricerca,
        filter_stato=filter_stato,
        stats=stats,
        cinemas=cinemas,
        chat_info=chat_info,
        single_cinema=single_cinema,
        new_ticket_ids=new_ticket_ids,
    )


# --- DETTAGLIO TICKET ---
@app.route("/problems/<int:problem_id>", methods=["GET"])
def ticket_detail(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    comments = store.get_comments(p.id)
    allegati = _get_allegati(p.cinema, p.id)
    store.upsert_ticket_read(session["user_id"], p.id)
    return render_template("ticket_detail.html", problem=p, comments=comments, allegati=allegati)


# --- AGGIUNGI COMMENTO ---
@app.route("/problems/<int:problem_id>/comment", methods=["POST"])
def add_comment(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    testo = request.form.get("testo", "").strip()
    if testo:
        store.add_comment(p.id, session["username"], session["role"], testo)
        if session["role"] != "admin":
            # Scrive un cliente -> avvisa l'assistenza
            mailer.notifica_nuovo_messaggio(p, session["username"], testo)
        else:
            cliente = store.get_user_by_username(p.autore)
            if cliente and cliente.email:
                mailer.notifica_risposta_al_cliente(p, cliente.email, testo)
    return redirect(url_for("ticket_detail", problem_id=p.id) + "#chat-bottom")


# --- UPLOAD ALLEGATO ---
@app.route("/problems/<int:problem_id>/upload", methods=["POST"])
def upload_allegato(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    f = request.files.get("allegato")
    if not f or not f.filename:
        flash("Nessun file selezionato.", "warning")
        return redirect(url_for("ticket_detail", problem_id=problem_id))
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        flash(f"Tipo file non consentito (.{ext}).", "danger")
        return redirect(url_for("ticket_detail", problem_id=problem_id))
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > MAX_FILE_SIZE:
        flash("File troppo grande (max 50 MB).", "danger")
        return redirect(url_for("ticket_detail", problem_id=problem_id))
    safe_name = secure_filename(f.filename)
    folder = os.path.join(ALLEGATI_FOLDER, _cinema_folder(p.cinema))
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"{problem_id}_{safe_name}")
    # Se esiste già, aggiungi suffisso numerico
    if os.path.exists(dest):
        base, dot_ext = os.path.splitext(f"{problem_id}_{safe_name}")
        counter = 1
        while os.path.exists(os.path.join(folder, f"{base}_{counter}{dot_ext}")):
            counter += 1
        dest = os.path.join(folder, f"{base}_{counter}{dot_ext}")
    f.save(dest)
    flash("Allegato caricato con successo.", "success")
    return redirect(url_for("ticket_detail", problem_id=problem_id))


# --- DOWNLOAD ALLEGATO ---
@app.route("/allegati/<path:cinema_folder>/<path:filename>")
def download_allegato(cinema_folder, filename):
    if "user_id" not in session:
        return redirect(url_for("login"))
    # Sicurezza: no path traversal
    safe_cinema = _cinema_folder(cinema_folder)
    safe_file   = secure_filename(filename)
    filepath = os.path.join(ALLEGATI_FOLDER, safe_cinema, safe_file)
    if not os.path.isfile(filepath):
        abort(404)
    # Ricava ticket_id dal nome file per verificare accesso
    try:
        ticket_id = int(safe_file.split("_")[0])
        p = store.get_problem_by_id(ticket_id)
        if p and not _puo_vedere(p):
            return "Accesso negato", 403
    except (ValueError, IndexError):
        if session["role"] != "admin":
            return "Accesso negato", 403
    return send_file(filepath, as_attachment=True,
                     download_name=safe_file[len(safe_file.split("_")[0]) + 1:])



# --- ELIMINA ALLEGATO ---
@app.route("/allegati/<path:cinema_folder>/<path:filename>/delete", methods=["POST"])
def delete_allegato(cinema_folder, filename):
    if "user_id" not in session:
        return redirect(url_for("login"))
    safe_cinema = _cinema_folder(cinema_folder)
    safe_file   = secure_filename(filename)
    filepath = os.path.join(ALLEGATI_FOLDER, safe_cinema, safe_file)
    if not os.path.isfile(filepath):
        abort(404)
    try:
        ticket_id = int(safe_file.split("_")[0])
    except (ValueError, IndexError):
        ticket_id = None
    if session["role"] != "admin":
        if ticket_id:
            p = store.get_problem_by_id(ticket_id)
            if not p or not _puo_vedere(p):
                return "Accesso negato", 403
        else:
            return "Accesso negato", 403
    os.remove(filepath)
    flash("Allegato eliminato.", "success")
    if ticket_id:
        return redirect(url_for("ticket_detail", problem_id=ticket_id))
    return redirect(url_for("dashboard"))



# --- AGGIORNA TICKET (stato/urgenza) ---
@app.route("/problems/<int:problem_id>/update", methods=["POST"])
def update_ticket(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    nuovo_stato   = request.form.get("stato", p.stato)
    nuova_urgenza = request.form.get("urgenza", p.urgenza)
    stato_prima   = p.stato
    urgenza_prima = p.urgenza
    if nuovo_stato == "Chiuso" and p.stato != "Chiuso":
        p.chiuso_da = session["username"]
        p.chiuso_il = datetime.utcnow()
    elif nuovo_stato != "Chiuso":
        p.chiuso_da = None
        p.chiuso_il = None
    p.stato   = nuovo_stato
    p.urgenza = nuova_urgenza
    store.update_problem(p)

    # Avvisa il cliente del cambiamento, se l'ha fatto l'assistenza: quando
    # e' lui stesso a modificare il ticket saprebbe gia' di averlo fatto.
    if session["role"] == "admin" and session["username"] != p.autore:
        cliente = store.get_user_by_username(p.autore)
        if cliente and cliente.email:
            mailer.notifica_cambio_stato(p, cliente.email, stato_prima, urgenza_prima)

    flash("Ticket aggiornato.", "success")
    if nuovo_stato == "Chiuso":
        return redirect(url_for("closed_tickets"))
    return redirect(url_for("ticket_detail", problem_id=p.id))


# --- ARCHIVIO TICKET CHIUSI ---
@app.route("/closed")
def closed_tickets():
    if "user_id" not in session:
        return redirect(url_for("login"))
    e_admin = session["role"] == "admin"
    ricerca = request.args.get("q", "").strip()
    try:
        pagina = max(1, int(request.args.get("p", "1")))
    except ValueError:
        pagina = 1

    tutti = store.get_problems_filtered(
        stato_eq="Chiuso",
        autore=None if e_admin else session["username"],
        cinemas=None if e_admin else _cinema_utente(),
        ricerca=ricerca or None,
    )

    # Paginazione: l'archivio cresce senza limite, caricarlo tutto
    # in una pagina sola diventa presto impraticabile.
    per_pagina = 50
    totale  = len(tutti)
    pagine  = max(1, (totale + per_pagina - 1) // per_pagina)
    pagina  = min(pagina, pagine)
    inizio  = (pagina - 1) * per_pagina
    problems = tutti[inizio:inizio + per_pagina]

    return render_template("closed_tickets.html", problems=problems,
                           ricerca=ricerca, pagina=pagina, pagine=pagine,
                           totale=totale)


# --- AGGIUNGI PROBLEMA ---
@app.route("/problems/add", methods=["POST"])
def add_problem():
    if "user_id" not in session:
        return redirect(url_for("login"))
    cinema_nome = request.form.get("cinema", "").strip()
    sala    = request.form.get("sala", "1").strip()
    tipo    = request.form.get("tipo", "").strip()
    urgenza = request.form.get("urgenza", "Non urgente")
    stato   = request.form.get("stato", "Aperto")
    if not cinema_nome or not tipo:
        flash("Compila tutti i campi.", "danger")
        return redirect(url_for("dashboard"))
    cinema_obj = store.get_cinema_by_nome(cinema_nome)
    città = cinema_obj.città if cinema_obj else ""
    nuovo = store.create_problem(cinema=cinema_nome, città=città, sala=sala,
                                 tipo=tipo, urgenza=urgenza, stato=stato,
                                 autore=session["username"])
    # Notifica solo se il ticket è aperto da un cliente (non da un admin)
    if session["role"] != "admin":
        mailer.notifica_nuovo_ticket(nuovo)
    flash("Problema aggiunto con successo.", "success")
    return redirect(url_for("dashboard"))


# --- MODIFICA PROBLEMA ---
@app.route("/problems/<int:problem_id>/edit", methods=["GET", "POST"])
def edit_problem(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    if request.method == "POST":
        p.cinema  = request.form.get("cinema", p.cinema)
        p.tipo    = request.form.get("tipo", p.tipo)
        p.urgenza = request.form.get("urgenza", p.urgenza)
        p.stato   = request.form.get("stato", p.stato)
        store.update_problem(p)
        flash("Problema aggiornato con successo.", "success")
        return redirect(url_for("dashboard"))
    cinemas = store.get_all_cinemas()
    return render_template("edit_problem.html", problem=p, cinemas=cinemas)


# --- ARCHIVIA PROBLEMA ---
@app.route("/problems/<int:problem_id>/delete", methods=["POST"])
def delete_problem(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    if not _puo_vedere(p):
        return "Accesso negato", 403
    p.stato = "Chiuso"
    store.update_problem(p)
    flash("Ticket archiviato.", "success")
    return redirect(url_for("dashboard"))


# --- ELIMINA DEFINITIVAMENTE (solo admin) ---
@app.route("/problems/<int:problem_id>/destroy", methods=["POST"])
def destroy_problem(problem_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session["role"] != "admin":
        return "Accesso negato", 403
    p = store.get_problem_by_id(problem_id)
    if not p:
        abort(404)
    store.delete_problem(problem_id)
    flash("Ticket eliminato definitivamente.", "success")
    return redirect(url_for("closed_tickets"))


# --- IMPOSTAZIONI NOTIFICHE (solo admin) ---
@app.route("/impostazioni", methods=["GET", "POST"])
def impostazioni_notifiche():
    if session.get("role") != "admin":
        return "Accesso negato", 403

    if request.method == "POST":
        azione = request.form.get("azione", "salva")

        impostazioni.salva({
            "smtp_host":     request.form.get("smtp_host", ""),
            "smtp_port":     request.form.get("smtp_port", ""),
            "smtp_ssl":      "1" if request.form.get("smtp_ssl") else "0",
            "smtp_user":     request.form.get("smtp_user", ""),
            # vuoto = lascia quella già salvata
            "smtp_password": request.form.get("smtp_password", ""),
            "smtp_from":     request.form.get("smtp_from", ""),
            "notify_email":  request.form.get("notify_email", ""),
            "app_base_url":  request.form.get("app_base_url", ""),
        })

        if azione == "prova":
            mancanti = impostazioni.campi_mancanti()
            if mancanti:
                elenco = ", ".join(f"«{m}»" for m in mancanti)
                flash(f"Manca ancora: {elenco}. "
                      f"Compila e riprova.", "warning")
                return redirect(url_for("impostazioni_notifiche"))
            destinatario = impostazioni.leggi("notify_email")
            try:
                # Si usa lo stesso modello delle notifiche vere: così la
                # prova mostra davvero come arriveranno, logo compreso.
                mailer.invia_adesso(
                    "[SigraFilm NOC] Prova invio notifiche",
                    mailer._wrap(
                        "Prova riuscita", "#16a34a",
                        [("Casella", impostazioni.leggi("smtp_user")),
                         ("Server", impostazioni.leggi("smtp_host"))],
                        '<p style="margin:20px 0 0;color:#374151;font-size:14px;'
                        'line-height:1.5;">Se leggi questo messaggio le notifiche '
                        'funzionano: le segnalazioni dei clienti arriveranno '
                        'qui, con questo aspetto.</p>',
                        "",
                    ),
                    "Se leggi questo messaggio, le notifiche del NOC funzionano.",
                    destinatario,
                )
                flash(f"Email di prova inviata a {destinatario}. "
                      f"Controlla la casella, guarda anche nello spam.", "success")
            except Exception as e:
                flash(f"Invio fallito: {_spiega_errore_invio(e)}", "danger")
        else:
            flash("Impostazioni salvate.", "success")

        return redirect(url_for("impostazioni_notifiche"))

    imp = impostazioni.tutte()
    return render_template("impostazioni.html", imp=imp,
                           configurato=impostazioni.configurato())


def _spiega_errore_invio(e: Exception) -> str:
    """Traduce l'errore tecnico in una spiegazione utile."""
    testo = str(e)
    tipo = type(e).__name__

    if "timed out" in testo.lower() or tipo == "timeout":
        return ("il server non risponde (timeout). Di solito significa che la "
                "porta è bloccata dall'antivirus, dal firewall di Windows o "
                "dal router. Prova a disattivare la protezione posta "
                "dell'antivirus, oppure la porta 25 invece della 465.")
    if "authentication" in testo.lower() or "535" in testo or "AUTH" in testo:
        return ("utente o password rifiutati dal server di posta. Se la casella "
                "ha la verifica in due passaggi serve una «password per le app».")
    if "Name or service not known" in testo or "getaddrinfo" in testo:
        return "il nome del server non esiste: controlla di averlo scritto giusto."
    if "Connection refused" in testo:
        return "il server rifiuta la connessione su quella porta: controlla il numero di porta."
    # I messaggi che scriviamo noi sono gia' in italiano: mostrali cosi' come sono
    if tipo in ("RuntimeError", "ValueError"):
        return testo
    return f"{tipo}: {testo[:200]}"


# --- GESTIONE UTENTI ---
@app.route("/users", methods=["GET", "POST"])
def admin_users():
    if session.get("role") != "admin":
        return "Accesso negato", 403
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role     = request.form.get("role", "user")
        telefono = request.form.get("telefono", "").strip()
        email    = request.form.get("email", "").strip()
        if not username or len(password) < 8:
            flash("Username obbligatorio e password di almeno 8 caratteri.", "danger")
            return redirect(url_for("admin_users"))
        if store.get_user_by_username(username):
            flash("Username già in uso.", "warning")
            return redirect(url_for("admin_users"))
        nuovo = store.create_user(username=username, password_hash=generate_password_hash(password),
                                  password_plain=password,
                                  role=role, telefono=telefono, email=email)
        # I cinema si assegnano dopo, dalla pagina di dettaglio: qui l'elenco
        # sarebbe lungo un centinaio di voci e allungherebbe il modulo senza
        # motivo, visto che serve una sola volta.
        if role == "admin":
            flash(f"Amministratore «{username}» creato. Vede tutti i cinema.", "success")
        else:
            flash(f"Utente «{username}» creato. Ora assegnagli i cinema con il "
                  f"pulsante 🎬 nella sua riga.", "success")
        return redirect(url_for("admin_users"))
    # Le richieste di registrazione vanno in cima: sono l'unica riga su cui
    # c'è qualcosa da fare, e in fondo a un elenco lungo passerebbero inosservate.
    users_list = sorted(store.get_all_users(),
                        key=lambda u: (0 if u.stato == "richiesta" else 1, u.id))
    in_attesa = sum(1 for u in users_list if u.stato == "richiesta")
    all_cinemas = store.get_all_cinemas(order_by="città_nome")
    # Cinema già assegnati, per mostrarli nella tabella
    assegnati = {u.id: store.get_cinema_ids_for_user(u.id) for u in users_list}
    nomi_cinema = {c.id: c.nome for c in all_cinemas}
    return render_template("users.html", users=users_list, all_cinemas=all_cinemas,
                           assegnati=assegnati, nomi_cinema=nomi_cinema,
                           in_attesa=in_attesa)


# --- DETTAGLIO UTENTE ---
@app.route("/users/<int:user_id>", methods=["GET", "POST"])
def user_detail(user_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    u = store.get_user_by_id(user_id)
    if not u:
        abort(404)
    if request.method == "POST":
        # La stessa pagina gestisce due moduli distinti: i recapiti e i
        # cinema assegnati. Si riconoscono dal campo "azione".
        if request.form.get("azione") == "recapiti":
            nuovo_nome = request.form.get("username", "").strip()
            if not nuovo_nome:
                flash("Lo username non può essere vuoto.", "danger")
                return redirect(url_for("user_detail", user_id=u.id))
            altro = store.get_user_by_username(nuovo_nome)
            if altro and altro.id != u.id:
                flash(f"Lo username «{nuovo_nome}» è già in uso.", "warning")
                return redirect(url_for("user_detail", user_id=u.id))

            vecchio_nome = u.username
            u.username = nuovo_nome
            u.nome     = request.form.get("nome", "").strip()
            u.telefono = request.form.get("telefono", "").strip()
            u.email    = request.form.get("email", "").strip()
            store.update_user(u)

            # I ticket registrano l'autore per nome, non per identificativo:
            # senza questo allineamento l'utente perderebbe i propri ticket.
            if nuovo_nome != vecchio_nome:
                for p in store.get_all_problems():
                    if p.autore == vecchio_nome:
                        p.autore = nuovo_nome
                        store.update_problem(p)
                flash(f"Utente rinominato in «{nuovo_nome}». "
                      f"Aggiornati anche i suoi ticket.", "success")
            else:
                flash("Recapiti aggiornati.", "success")
            return redirect(url_for("user_detail", user_id=u.id))

        cinema_ids = [int(x) for x in request.form.getlist("cinema_ids") if x.isdigit()]
        store.set_user_cinemas(u.id, cinema_ids)
        flash(f"Cinema assegnati a '{u.username}' aggiornati.", "success")
        return redirect(url_for("user_detail", user_id=u.id))
    all_cinemas  = store.get_all_cinemas(order_by="città_nome")
    assigned_ids = set(store.get_cinema_ids_for_user(u.id))
    return render_template("user_detail.html", u=u, all_cinemas=all_cinemas, assigned_ids=assigned_ids)


# --- INVIA CREDENZIALI AL NUOVO UTENTE ---
@app.route("/users/<int:user_id>/credenziali", methods=["POST"])
def invia_credenziali(user_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    u = store.get_user_by_id(user_id)
    if not u:
        abort(404)

    # Le password sono salvate cifrate e non si possono rileggere: se ne
    # genera una nuova e si manda quella. Caratteri senza ambiguita' tra
    # lettere e cifre, perche' spesso viene ricopiata a mano.
    alfabeto = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    password = "".join(secrets.choice(alfabeto) for _ in range(12))

    cinema = [c.nome for c in store.get_cinemas_by_ids(
        store.get_cinema_ids_for_user(u.id))] if u.role != "admin" else []

    try:
        mailer.invia_credenziali(u.username, password, u.email, cinema)
    except Exception as e:
        flash(f"Invio non riuscito: {_spiega_errore_invio(e)}", "danger")
        return redirect(url_for("admin_users"))

    # La password si cambia solo dopo che l'invio e' partito: se fallisse,
    # l'utente resterebbe con una password che non conosce nessuno.
    era_richiesta = u.stato == "richiesta"
    u.password_hash  = generate_password_hash(password)
    u.password_plain = password
    u.stato          = "attivo"      # da qui in poi puo' entrare
    store.update_user(u)

    if era_richiesta:
        flash(f"Richiesta approvata: «{u.username}» ha ricevuto le credenziali "
              f"a {u.email} e può entrare.", "success")
    else:
        flash(f"Credenziali inviate a {u.email}. "
              f"La password di «{u.username}» è stata rigenerata.", "success")
    return redirect(url_for("admin_users"))


# --- RESET PASSWORD ---
@app.route("/users/<int:user_id>/reset", methods=["POST"])
def reset_password(user_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    new_password = request.form.get("new_password", "").strip()
    if len(new_password) < 8:
        flash("La nuova password deve avere almeno 8 caratteri.", "danger")
        return redirect(url_for("admin_users"))
    u = store.get_user_by_id(user_id)
    if not u:
        abort(404)
    u.password_hash  = generate_password_hash(new_password)
    u.password_plain = new_password
    # Se era una richiesta in attesa, scegliergli la password a mano vale
    # come approvazione: altrimenti resterebbe bloccato fuori con una
    # password valida in mano.
    u.stato          = "attivo"
    store.update_user(u)
    flash(f"Password di '{u.username}' aggiornata con successo.", "success")
    return redirect(url_for("admin_users"))


# --- ELIMINA UTENTE ---
@app.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    if session.get("user_id") == user_id:
        flash("Non puoi eliminare il tuo stesso utente mentre sei loggato.", "warning")
        return redirect(url_for("admin_users"))
    u = store.get_user_by_id(user_id)
    if not u:
        abort(404)
    if u.role == "admin" and store.count_admins() <= 1:
        flash("Non puoi eliminare l'unico admin rimasto.", "warning")
        return redirect(url_for("admin_users"))
    username = u.username
    store.delete_user(user_id)
    flash(f"Utente '{username}' eliminato.", "success")
    return redirect(url_for("admin_users"))


# --- GESTIONE CINEMA ---
@app.route("/admin/cinemas", methods=["GET", "POST"])
def admin_cinemas():
    if session.get("role") != "admin":
        return "Accesso negato", 403

    if request.method == "POST" and request.form.get("azione") == "importa":
        # Sostituisce l'anagrafica con i cinema reali del Support Tool,
        # ricollegando le assegnazioni utente anche se il nome cambia.
        try:
            import importa_cinema
            esito = importa_cinema.importa(store)
            flash(f"Importati {esito['inseriti']} cinema dal Support Tool. "
                  f"Assegnazioni ricollegate: {esito['ricollegate']}."
                  + (f" Perse: {esito['perse']}." if esito["perse"] else ""),
                  "success")
        except Exception as e:
            flash(f"Importazione non riuscita: {e}", "danger")
        return redirect(url_for("admin_cinemas"))

    if request.method == "POST":
        nome     = request.form.get("nome", "").strip()
        città    = request.form.get("città", "").strip()
        telefono = request.form.get("telefono", "").strip()
        indirizzo= request.form.get("indirizzo", "").strip()
        try:
            num_sale = max(1, int(request.form.get("num_sale", "1")))
        except ValueError:
            num_sale = 1
        if nome:
            store.create_cinema(nome=nome, città=città, num_sale=num_sale,
                                telefono=telefono, indirizzo=indirizzo)
            flash(f"Cinema '{nome}' ({città}) aggiunto.", "success")
        return redirect(url_for("admin_cinemas"))

    cinemas = store.get_all_cinemas(order_by="città_nome")
    _urgency_order = {"Critico": 0, "Urgente": 1, "Non urgente": 2}
    open_problems = store.get_problems_filtered(stato_ne="Chiuso")
    open_problems.sort(key=lambda p: _urgency_order.get(p.urgenza, 9))
    tickets_map = {}
    for p in open_problems:
        key = (p.cinema or "").strip()
        if key:
            tickets_map.setdefault(key, []).append(p)

    # Chi gestisce ogni cinema. Solo gli utenti normali: gli amministratori
    # vedono tutti i cinema per definizione, elencarli su ogni riga sarebbe
    # rumore senza informazione.
    gestori = {}
    for u in store.get_all_users():
        if u.role == "admin":
            continue
        for cid in store.get_cinema_ids_for_user(u.id):
            gestori.setdefault(cid, []).append(u.username)
    for lista in gestori.values():
        lista.sort()

    return render_template("cinemas.html", cinemas=cinemas,
                           tickets_map=tickets_map, gestori=gestori)


@app.route("/miei-cinema", methods=["GET", "POST"])
def miei_cinema():
    """
    I cinema assegnati all'utente, con telefono e indirizzo modificabili.

    Sono i due dati che cambiano piu' spesso e che il cliente conosce meglio
    di noi: prima bisognava scriverci per farli correggere. Nome, citta' e
    numero di sale restano all'amministratore, perche' toccarli rinomina il
    cinema anche sui ticket gia' aperti.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_cinemas"))   # lui ha la pagina completa

    suoi = store.get_cinema_ids_for_user(session["user_id"])

    if request.method == "POST":
        try:
            cid = int(request.form.get("cinema_id", ""))
        except ValueError:
            abort(400)
        # Il controllo qui e' quello che conta: il modulo mostra solo i suoi
        # cinema, ma l'identificativo arriva dal browser e si puo' cambiare.
        if cid not in suoi:
            return "Accesso negato", 403
        c = store.get_cinema_by_id(cid)
        if not c:
            abort(404)
        c.telefono  = request.form.get("telefono", "").strip()[:40]
        c.indirizzo = request.form.get("indirizzo", "").strip()[:200]
        store.update_cinema(c)
        flash(f"Recapiti di «{c.nome}» aggiornati.", "success")
        return redirect(url_for("miei_cinema"))

    cinemas = sorted(store.get_cinemas_by_ids(suoi),
                     key=lambda c: ((c.città or "").lower(), c.nome.lower()))
    return render_template("miei_cinema.html", cinemas=cinemas)


@app.route("/admin/cinemas/<int:cinema_id>/edit", methods=["GET", "POST"])
def edit_cinema(cinema_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    c = store.get_cinema_by_id(cinema_id)
    if not c:
        abort(404)
    if request.method == "POST":
        nuovo_nome  = request.form.get("nome", "").strip()
        nuova_città = request.form.get("città", "").strip()
        try:
            num_sale = max(1, int(request.form.get("num_sale", "1")))
        except ValueError:
            num_sale = 1
        try:
            lat = float(request.form.get("lat", "").strip()) if request.form.get("lat", "").strip() else None
            lng = float(request.form.get("lng", "").strip()) if request.form.get("lng", "").strip() else None
        except ValueError:
            lat = lng = None
        if nuovo_nome:
            c.nome     = nuovo_nome
            c.città    = nuova_città
            c.num_sale = num_sale
            c.telefono = request.form.get("telefono", "").strip()
            c.indirizzo= request.form.get("indirizzo", "").strip()
            c.lat      = lat
            c.lng      = lng
            store.update_cinema(c)
            flash(f"Cinema '{nuovo_nome}' aggiornato.", "success")
        return redirect(url_for("admin_cinemas"))
    return render_template("edit_cinema.html", c=c)


@app.route("/admin/cinemas/<int:cinema_id>/etichetta")
def etichetta_cinema(cinema_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    if not _reportlab_ok:
        return "Libreria PDF non installata. Eseguire: pip install reportlab", 500
    c = store.get_cinema_by_id(cinema_id)
    if not c:
        abort(404)

    buf = io.BytesIO()
    W, H = A4  # 595.27 x 841.89 pt

    cv = rl_canvas.Canvas(buf, pagesize=A4)

    # ── Palette ──────────────────────────────────────────────
    nero      = colors.HexColor("#1a1a1a")
    grigio    = colors.HexColor("#444444")
    grigio_bg = colors.HexColor("#f5f5f5")
    bianco    = colors.white

    # ── Helper: linea separatrice ─────────────────────────────
    def hrule(y, spessore=0.5, col=grigio):
        cv.setStrokeColor(col)
        cv.setLineWidth(spessore)
        cv.line(20*mm, y, W - 20*mm, y)

    # ══════════════════════════════════════════════════════════
    # CORNICE ESTERNA
    # ══════════════════════════════════════════════════════════
    margin = 15*mm
    cv.setStrokeColor(nero)
    cv.setLineWidth(2)
    cv.rect(margin, margin, W - 2*margin, H - 2*margin, stroke=1, fill=0)

    # ══════════════════════════════════════════════════════════
    # INTESTAZIONE  (striscia scura in cima)
    # ══════════════════════════════════════════════════════════
    header_h = 28*mm
    header_y = H - margin - header_h
    cv.setFillColor(nero)
    cv.rect(margin, header_y, W - 2*margin, header_h, stroke=0, fill=1)

    cv.setFillColor(bianco)
    cv.setFont("Helvetica-Bold", 17)
    cv.drawCentredString(W/2, header_y + 16*mm, "SIGRAFILM S.A.S – CINEMECCANICA")
    cv.setFont("Helvetica", 10)
    cv.drawCentredString(W/2, header_y + 9*mm, "Distribuzione e assistenza apparecchiature cinematografiche")
    cv.setFont("Helvetica-Oblique", 8)
    cv.drawCentredString(W/2, header_y + 3.5*mm, "ETICHETTA DI SPEDIZIONE")

    # ══════════════════════════════════════════════════════════
    # SEZIONE MITTENTE
    # ══════════════════════════════════════════════════════════
    mit_top = header_y - 8*mm
    mit_h   = 70*mm
    mit_y   = mit_top - mit_h

    # sfondo chiaro
    cv.setFillColor(grigio_bg)
    cv.rect(margin, mit_y, W - 2*margin, mit_h, stroke=0, fill=1)

    # etichetta "MITTENTE"
    cv.setFillColor(nero)
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(margin + 5*mm, mit_top - 5*mm, "MITTENTE")
    hrule(mit_top - 7*mm, spessore=1, col=nero)

    # dati mittente
    mit_lines = [
        ("Helvetica-Bold", 16, "SIGRAFILM S.A.S – CINEMECCANICA"),
        ("Helvetica", 12,      "Via Sant'Antonino 7r"),
        ("Helvetica", 12,      "50123 FIRENZE (FI)"),
        ("Helvetica", 11,      "Tel. 055 290746   Cell. 338-1025100"),
        ("Helvetica-Oblique", 10, "sigrafilm@mclink.it"),
    ]
    ty = mit_top - 14*mm
    for font, size, testo in mit_lines:
        cv.setFont(font, size)
        cv.setFillColor(nero if size >= 12 else grigio)
        cv.drawString(margin + 7*mm, ty, testo)
        ty -= (size + 4)

    # ══════════════════════════════════════════════════════════
    # FRECCIA / DIVISORE
    # ══════════════════════════════════════════════════════════
    arrow_y = mit_y - 10*mm
    hrule(arrow_y + 5*mm, spessore=0.5)
    cv.setFillColor(nero)
    cv.setFont("Helvetica-Bold", 22)
    cv.drawCentredString(W/2, arrow_y - 3*mm, "▼")

    # ══════════════════════════════════════════════════════════
    # SEZIONE DESTINATARIO
    # ══════════════════════════════════════════════════════════
    dest_top = arrow_y - 14*mm
    dest_h   = 100*mm
    dest_y   = dest_top - dest_h

    cv.setFillColor(bianco)
    cv.setStrokeColor(nero)
    cv.setLineWidth(1.5)
    cv.rect(margin, dest_y, W - 2*margin, dest_h, stroke=1, fill=1)

    cv.setFillColor(nero)
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(margin + 5*mm, dest_top - 5*mm, "DESTINATARIO")
    hrule(dest_top - 7*mm, spessore=1, col=nero)

    # dati destinatario
    dest_nome     = (c.nome or "").upper()
    dest_indirizzo= (c.indirizzo or "")
    dest_città    = (c.città or "")
    dest_tel      = (c.telefono or "")

    ty = dest_top - 16*mm
    cv.setFillColor(nero)
    cv.setFont("Helvetica-Bold", 22)
    cv.drawString(margin + 7*mm, ty, dest_nome)
    ty -= 28

    if dest_indirizzo:
        cv.setFont("Helvetica", 16)
        cv.setFillColor(grigio)
        cv.drawString(margin + 7*mm, ty, dest_indirizzo)
        ty -= 22

    if dest_città:
        cv.setFont("Helvetica-Bold", 16)
        cv.setFillColor(nero)
        cv.drawString(margin + 7*mm, ty, dest_città)
        ty -= 22

    if dest_tel:
        cv.setFont("Helvetica", 12)
        cv.setFillColor(grigio)
        cv.drawString(margin + 7*mm, ty, f"Tel. {dest_tel}")

    # ══════════════════════════════════════════════════════════
    # PIE' DI PAGINA
    # ══════════════════════════════════════════════════════════
    footer_y = margin + 5*mm
    cv.setFont("Helvetica-Oblique", 7)
    cv.setFillColor(grigio)
    cv.drawCentredString(W/2, footer_y, f"Generata il {date.today().strftime('%d/%m/%Y')} — SigraFilm NOC")

    cv.save()
    buf.seek(0)
    nome_file = f"etichetta_{c.nome.replace(' ', '_')}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=nome_file)


@app.route("/admin/cinemas/<int:cinema_id>/delete", methods=["POST"])
def delete_cinema(cinema_id):
    if session.get("role") != "admin":
        return "Accesso negato", 403
    c = store.get_cinema_by_id(cinema_id)
    if c:
        nome = c.nome
        store.delete_cinema(cinema_id)
        flash(f"Cinema '{nome}' eliminato.", "success")
    return redirect(url_for("admin_cinemas"))


# --- EXPORT EXCEL ---
@app.route("/export/excel")
def export_excel():
    if "user_id" not in session:
        return redirect(url_for("login"))

    is_admin = session["role"] == "admin"
    username = session["username"]
    foglio   = request.args.get("foglio", "tutto")

    wb = openpyxl.Workbook()
    header_font  = Font(bold=True, color="FFFFFF")
    header_fill  = PatternFill("solid", fgColor="1F2937")
    center_align = Alignment(horizontal="center", vertical="center")

    def style_header(ws, headers):
        ws.append(headers)
        for cell in ws[1]:
            cell.font      = header_font
            cell.fill      = header_fill
            cell.alignment = center_align

    def autowidth(ws):
        for col in ws.columns:
            max_len = max((len(str(c.value)) if c.value else 0) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    def fmt(dt):
        return dt.strftime("%d/%m/%Y %H:%M") if dt else ""

    first_sheet = True

    def new_sheet(title):
        nonlocal first_sheet
        if first_sheet:
            ws = wb.active
            ws.title = title
            first_sheet = False
        else:
            ws = wb.create_sheet(title)
        return ws

    if foglio in ("aperti", "tutto"):
        ws = new_sheet("Ticket Aperti")
        q = store.get_problems_filtered(stato_ne="Chiuso",
                                        autore=username if not is_admin else None)
        style_header(ws, ["ID", "Cinema", "Città", "Sala", "Descrizione", "Urgenza", "Stato", "Autore", "Data apertura"])
        for p in q:
            ws.append([p.id, p.cinema, p.città, p.sala, p.tipo, p.urgenza, p.stato, p.autore, fmt(p.data_ora)])
        autowidth(ws)

    if foglio in ("chiusi", "tutto"):
        ws = new_sheet("Archivio Chiusi")
        q2 = store.get_problems_filtered(stato_eq="Chiuso",
                                         autore=username if not is_admin else None)
        style_header(ws, ["ID", "Cinema", "Città", "Sala", "Descrizione", "Urgenza", "Autore", "Data apertura", "Chiuso da", "Chiuso il"])
        for p in q2:
            ws.append([p.id, p.cinema, p.città, p.sala, p.tipo, p.urgenza, p.autore, fmt(p.data_ora), p.chiuso_da or "", fmt(p.chiuso_il)])
        autowidth(ws)

    if foglio in ("cinema", "tutto") and is_admin:
        ws = new_sheet("Cinema")
        style_header(ws, ["ID", "Nome", "Città", "Sale", "Telefono", "Indirizzo", "Lat", "Lng"])
        for c in store.get_all_cinemas(order_by="città_nome"):
            ws.append([c.id, c.nome, c.città, c.num_sale, c.telefono, c.indirizzo, c.lat or "", c.lng or ""])
        autowidth(ws)

    if foglio in ("utenti", "tutto") and is_admin:
        ws = new_sheet("Utenti")
        style_header(ws, ["ID", "Username", "Nome e cognome", "Ruolo",
                          "Email", "Telefono", "Stato"])
        for u in sorted(store.get_all_users(), key=lambda x: x.id):
            stato = "In attesa di approvazione" if u.stato == "richiesta" else "Attivo"
            ws.append([u.id, u.username, u.nome, u.role, u.email, u.telefono, stato])
        autowidth(ws)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    now = datetime.now().strftime("%Y%m%d_%H%M")
    nomi = {"aperti": "ticket_aperti", "chiusi": "archivio_chiusi",
            "cinema": "cinema", "utenti": "utenti", "tutto": "completo"}
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"sigrafilm_{nomi.get(foglio, foglio)}_{now}.xlsx",
    )


# --- IMPORT EXCEL ---
@app.route("/import/excel", methods=["GET", "POST"])
def import_excel():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session["role"] != "admin":
        return "Accesso negato", 403
    if request.method == "GET":
        return render_template("import_excel.html")

    f = request.files.get("file")
    if not f or not f.filename.endswith(".xlsx"):
        flash("Carica un file .xlsx valido.", "danger")
        return redirect(url_for("import_excel"))
    try:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    except Exception:
        flash("File non valido o corrotto.", "danger")
        return redirect(url_for("import_excel"))

    # Con "sostituisci" i cinema del file rimpiazzano l'anagrafica invece di
    # aggiungersi: altrimenti chi ne ha già a catalogo si ritrova i doppioni,
    # perché l'importazione salta i nomi che esistono già.
    if request.form.get("sostituisci_cinema") and "Cinema" in wb.sheetnames:
        elenco = []
        for riga in list(wb["Cinema"].iter_rows(values_only=True))[1:]:
            if not riga or not riga[1]:
                continue
            elenco.append({
                "nome": str(riga[1]).strip(),
                "città": str(riga[2] or "").strip(),
                "num_sale": riga[3] or 1,
                "telefono": str(riga[4] or "").strip(),
                "indirizzo": str(riga[5] or "").strip(),
                "lat": riga[6], "lng": riga[7],
            })
        if elenco:
            store.sostituisci_cinema(elenco)
            flash(f"Anagrafica sostituita: {len(elenco)} cinema. "
                  f"Ricontrolla le assegnazioni degli utenti dalla pagina Utenti.",
                  "success")
            return redirect(url_for("import_excel"))

    counts = store.import_from_workbook(wb)
    parts = []
    if counts["added_problems"]:   parts.append(f"{counts['added_problems']} ticket aggiunti")
    if counts["skipped_problems"]: parts.append(f"{counts['skipped_problems']} ticket già presenti (saltati)")
    if counts["added_cinemas"]:    parts.append(f"{counts['added_cinemas']} cinema aggiunti")
    if counts["skipped_cinemas"]:  parts.append(f"{counts['skipped_cinemas']} cinema già presenti (saltati)")
    if not parts:
        flash("Nessuna nuova riga trovata — tutto già presente.", "info")
    else:
        flash(" · ".join(parts) + ".", "success")
    return redirect(url_for("import_excel"))


# --- ERRORE 500 ---
@app.errorhandler(500)
def _internal_error(e):
    flash("Errore temporaneo del server. Riprova.", "warning")
    return redirect(request.referrer or url_for("dashboard"))


# --- MAIN ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
