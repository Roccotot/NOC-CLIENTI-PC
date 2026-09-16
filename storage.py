"""
storage.py — Layer di persistenza su file Excel per SigraFilm NOC.

Struttura cartella data/:
  data/utenti.xlsx        — utenti
  data/cinema.xlsx        — cinema
  data/cinema_eliminati.xlsx — cinema eliminati (tombstone)
  data/tickets.xlsx       — ticket (aperti + chiusi)
  data/commenti.xlsx      — commenti ai ticket
  data/letture.xlsx       — tracciamento lettura ticket per utente
  data/assegnazioni.xlsx  — assegnazioni utente→cinema
"""

import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from werkzeug.security import generate_password_hash

# ─── Percorso cartella dati ──────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Lock globale — protegge da scritture concorrenti
_lock = threading.Lock()


# ══════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════

@dataclass
class User:
    id: int
    username: str
    password_hash: str
    # Password leggibile, mostrata agli amministratori nella pagina Utenti.
    # Serve a poterla ricordare a chi la dimentica: dall'hash non si ricava.
    password_plain: str = ""
    role: str = "user"
    telefono: str = ""
    email: str = ""
    # "attivo" = puo' entrare nel sito.
    # "richiesta" = si e' registrato da solo dalla pagina di login e aspetta
    # che un amministratore gli mandi la password. Finche' resta cosi' non
    # ha una password valida e il login gli viene rifiutato.
    stato: str = "attivo"


@dataclass
class Problem:
    id: int
    cinema: str
    città: str
    sala: str
    tipo: str
    urgenza: str
    stato: str = "Aperto"
    chiuso_da: Optional[str] = None
    chiuso_il: Optional[datetime] = None
    autore: str = ""
    data_ora: Optional[datetime] = None

    def __post_init__(self):
        if self.data_ora is None:
            self.data_ora = datetime.utcnow()

    @property
    def comments(self):
        return store.get_comments(self.id)


@dataclass
class Comment:
    id: int
    problem_id: int
    autore: str
    role: str
    testo: str
    data_ora: Optional[datetime] = None

    def __post_init__(self):
        if self.data_ora is None:
            self.data_ora = datetime.utcnow()


@dataclass
class Cinema:
    id: int
    nome: str
    città: str = ""
    num_sale: int = 1
    telefono: str = ""
    indirizzo: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None


@dataclass
class TicketRead:
    id: int
    user_id: int
    problem_id: int
    last_read_at: Optional[datetime] = None

    def __post_init__(self):
        if self.last_read_at is None:
            self.last_read_at = datetime.utcnow()


@dataclass
class UserCinema:
    id: int
    user_id: int
    cinema_id: int


# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, name)


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _i(v, default=0) -> int:
    try:
        return int(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (ValueError, TypeError):
        return None


def _dt(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _fmt_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else ""


def _load_wb(filename: str, headers: list) -> openpyxl.Workbook:
    """Carica o crea un workbook con la riga header se non esiste."""
    path = _path(filename)
    if os.path.exists(path):
        try:
            return openpyxl.load_workbook(path)
        except Exception:
            pass
    wb = openpyxl.Workbook()
    ws = wb.active
    _write_header(ws, headers)
    wb.save(path)
    return wb


def _write_header(ws, headers: list):
    ws.append(headers)
    hfont = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font = hfont
        cell.fill = hfill
        cell.alignment = Alignment(horizontal="center")


BACKUP_DIR = os.path.join(DATA_DIR, "backup")
COPIE_BACKUP = 10          # quante copie tenere per ogni file
INTERVALLO_BACKUP = 3600   # secondi minimi tra due backup dello stesso file

_ultimo_backup: Dict[str, float] = {}


def _fai_backup(filename: str):
    """
    Conserva una copia del file prima di sovrascriverlo.

    Tiene le ultime COPIE_BACKUP versioni, al massimo una all'ora per file,
    così una modifica sbagliata o un file corrotto non sono definitivi.
    """
    percorso = _path(filename)
    if not os.path.exists(percorso):
        return
    adesso = time.time()
    if adesso - _ultimo_backup.get(filename, 0) < INTERVALLO_BACKUP:
        return
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        base = os.path.splitext(filename)[0]
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(percorso, os.path.join(BACKUP_DIR, f"{base}_{marca}.xlsx"))
        _ultimo_backup[filename] = adesso

        # Elimina le copie più vecchie oltre il limite
        copie = sorted(
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith(f"{base}_") and f.endswith(".xlsx")
        )
        for vecchia in copie[:-COPIE_BACKUP]:
            try:
                os.remove(os.path.join(BACKUP_DIR, vecchia))
            except OSError:
                pass
    except Exception as e:
        print(f"[backup] Impossibile salvare la copia di {filename}: {e}")


def _save_wb(wb: openpyxl.Workbook, filename: str):
    """
    Salvataggio atomico: scrive su un file temporaneo e solo a scrittura
    completata lo rinomina al posto dell'originale.

    Con il salvataggio diretto, un'interruzione a metà (PC spento, processo
    terminato) lasciava il file troncato e i dati dentro erano persi.
    Il rename è un'operazione atomica del filesystem: o c'è il file vecchio
    integro, o c'è quello nuovo completo. Mai una via di mezzo.
    """
    percorso = _path(filename)
    _fai_backup(filename)

    fd, temporaneo = tempfile.mkstemp(dir=os.path.dirname(percorso) or ".",
                                      prefix=f".{filename}.", suffix=".tmp")
    os.close(fd)
    try:
        wb.save(temporaneo)

        # Su Windows os.replace fallisce con "Accesso negato" se in quel
        # preciso istante il file e' aperto da qualcun altro: l'antivirus che
        # lo scansiona, Excel che lo tiene aperto, l'indicizzazione. Sono
        # blocchi che durano una frazione di secondo, quindi si riprova.
        ultimo = None
        for tentativo in range(6):
            try:
                os.replace(temporaneo, percorso)
                return
            except PermissionError as e:
                ultimo = e
                time.sleep(0.2 * (tentativo + 1))
        raise PermissionError(
            f"Impossibile salvare {filename}: il file risulta occupato da un "
            f"altro programma. Chiudilo se lo hai aperto in Excel, oppure "
            f"escludi la cartella data dalla scansione dell'antivirus. "
            f"({ultimo})")
    except Exception:
        try:
            os.remove(temporaneo)
        except OSError:
            pass
        raise


def _next_id(rows: list) -> int:
    if not rows:
        return 1
    return max((_i(r[0], 0) for r in rows), default=0) + 1


# ══════════════════════════════════════════════════════
# STORE — classe principale
# ══════════════════════════════════════════════════════

class ExcelStore:
    """
    Accesso completo ai dati tramite file Excel.
    Ogni metodo acquisisce il lock prima di leggere/scrivere.
    """

    HEADERS = {
        "utenti.xlsx":           ["id", "username", "password_hash", "password_plain", "role", "telefono", "email", "stato"],
        "cinema.xlsx":           ["id", "nome", "città", "num_sale", "telefono", "indirizzo", "lat", "lng"],
        "cinema_eliminati.xlsx": ["id", "nome"],
        "tickets.xlsx":          ["id", "cinema", "città", "sala", "tipo", "urgenza", "stato",
                                  "chiuso_da", "chiuso_il", "autore", "data_ora"],
        "commenti.xlsx":         ["id", "problem_id", "autore", "role", "testo", "data_ora"],
        "letture.xlsx":          ["id", "user_id", "problem_id", "last_read_at"],
        "assegnazioni.xlsx":     ["id", "user_id", "cinema_id"],
    }

    def _rows(self, filename: str) -> list:
        """Restituisce le righe (senza header) come lista di tuple."""
        wb = _load_wb(filename, self.HEADERS[filename])
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        return rows[1:] if len(rows) > 1 else []

    def _overwrite(self, filename: str, data_rows: list):
        """Riscrive il file Excel da zero con header + righe dati."""
        _ensure_dir()
        wb = openpyxl.Workbook()
        ws = wb.active
        _write_header(ws, self.HEADERS[filename])
        for row in data_rows:
            ws.append(row)
        _save_wb(wb, filename)

    # ── USERS ─────────────────────────────────────────

    def _row_to_user(self, r) -> User:
        return User(
            id=_i(r[0]), username=_s(r[1]), password_hash=_s(r[2]),
            password_plain=_s(r[3]), role=_s(r[4]) or "user",
            telefono=_s(r[5]), email=_s(r[6]),
            stato=(_s(r[7]) if len(r) > 7 else "") or "attivo",
        )

    def _user_to_row(self, u: User) -> tuple:
        return (u.id, u.username, u.password_hash, u.password_plain,
                u.role, u.telefono, u.email, u.stato)

    def get_all_users(self) -> List[User]:
        with _lock:
            return [self._row_to_user(r) for r in self._rows("utenti.xlsx")]

    def get_user_by_id(self, uid: int) -> Optional[User]:
        with _lock:
            for r in self._rows("utenti.xlsx"):
                if _i(r[0]) == uid:
                    return self._row_to_user(r)
        return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        with _lock:
            for r in self._rows("utenti.xlsx"):
                if _s(r[1]).lower() == username.lower():
                    return self._row_to_user(r)
        return None

    def create_user(self, username: str, password_hash: str,
                    password_plain: str = "",
                    role: str = "user", telefono: str = "", email: str = "",
                    stato: str = "attivo") -> User:
        with _lock:
            rows = self._rows("utenti.xlsx")
            new_id = _next_id(rows)
            u = User(id=new_id, username=username, password_hash=password_hash,
                     password_plain=password_plain,
                     role=role, telefono=telefono, email=email, stato=stato)
            rows.append(self._user_to_row(u))
            self._overwrite("utenti.xlsx", rows)
            return u

    def update_user(self, u: User):
        with _lock:
            rows = self._rows("utenti.xlsx")
            rows = [self._user_to_row(u) if _i(r[0]) == u.id else r for r in rows]
            self._overwrite("utenti.xlsx", rows)

    def delete_user(self, uid: int):
        with _lock:
            rows = [r for r in self._rows("utenti.xlsx") if _i(r[0]) != uid]
            self._overwrite("utenti.xlsx", rows)
            # rimuovi assegnazioni
            arows = [r for r in self._rows("assegnazioni.xlsx") if _i(r[1]) != uid]
            self._overwrite("assegnazioni.xlsx", arows)

    def count_admins(self) -> int:
        return sum(1 for u in self.get_all_users() if u.role == "admin")

    # ── PROBLEMS ──────────────────────────────────────

    def _row_to_problem(self, r) -> Problem:
        return Problem(
            id=_i(r[0]), cinema=_s(r[1]), città=_s(r[2]), sala=_s(r[3]) or "1",
            tipo=_s(r[4]), urgenza=_s(r[5]), stato=_s(r[6]) or "Aperto",
            chiuso_da=_s(r[7]) or None,
            chiuso_il=_dt(r[8]),
            autore=_s(r[9]),
            data_ora=_dt(r[10]) or datetime.utcnow(),
        )

    def _problem_to_row(self, p: Problem) -> tuple:
        return (p.id, p.cinema, p.città, p.sala, p.tipo, p.urgenza, p.stato,
                p.chiuso_da or "", _fmt_dt(p.chiuso_il), p.autore, _fmt_dt(p.data_ora))

    def get_all_problems(self) -> List[Problem]:
        with _lock:
            return [self._row_to_problem(r) for r in self._rows("tickets.xlsx")]

    def get_problem_by_id(self, pid: int) -> Optional[Problem]:
        with _lock:
            for r in self._rows("tickets.xlsx"):
                if _i(r[0]) == pid:
                    return self._row_to_problem(r)
        return None

    def get_problems_filtered(self, stato_ne: str = None, stato_eq: str = None,
                               autore: str = None, urgenza: str = None,
                               cinemas: List[str] = None,
                               ricerca: str = None) -> List[Problem]:
        """
        Elenco ticket filtrato.

        `autore` e `cinemas` si sommano: un utente vede i ticket che ha aperto
        lui PIU' quelli dei cinema che gli sono stati assegnati, così i colleghi
        dello stesso cinema vedono gli stessi ticket.
        `ricerca` cerca il testo in cinema, città, sala, descrizione, autore
        e numero del ticket.
        """
        problems = self.get_all_problems()
        if stato_ne:
            problems = [p for p in problems if p.stato != stato_ne]
        if stato_eq:
            problems = [p for p in problems if p.stato == stato_eq]

        if autore or cinemas:
            nomi = {c.strip().lower() for c in (cinemas or []) if c}
            problems = [
                p for p in problems
                if (autore and p.autore == autore)
                or (nomi and (p.cinema or "").strip().lower() in nomi)
            ]

        if urgenza:
            problems = [p for p in problems if p.urgenza == urgenza]

        if ricerca:
            q = ricerca.strip().lower()
            if q:
                problems = [
                    p for p in problems
                    if q in (p.cinema or "").lower()
                    or q in (p.città or "").lower()
                    or q in str(p.sala or "").lower()
                    or q in (p.tipo or "").lower()
                    or q in (p.autore or "").lower()
                    or q in f"#{p.id}"
                ]

        return sorted(problems, key=lambda p: p.data_ora or datetime.min, reverse=True)

    def create_problem(self, cinema: str, città: str, sala: str, tipo: str,
                       urgenza: str, stato: str, autore: str) -> Problem:
        with _lock:
            rows = self._rows("tickets.xlsx")
            new_id = _next_id(rows)
            p = Problem(id=new_id, cinema=cinema, città=città, sala=sala,
                        tipo=tipo, urgenza=urgenza, stato=stato, autore=autore,
                        data_ora=datetime.utcnow())
            rows.append(self._problem_to_row(p))
            self._overwrite("tickets.xlsx", rows)
            return p

    def update_problem(self, p: Problem):
        with _lock:
            rows = self._rows("tickets.xlsx")
            rows = [self._problem_to_row(p) if _i(r[0]) == p.id else r for r in rows]
            self._overwrite("tickets.xlsx", rows)

    def delete_problem(self, pid: int):
        with _lock:
            rows = [r for r in self._rows("tickets.xlsx") if _i(r[0]) != pid]
            self._overwrite("tickets.xlsx", rows)
            # rimuovi commenti e letture associati
            crows = [r for r in self._rows("commenti.xlsx") if _i(r[1]) != pid]
            self._overwrite("commenti.xlsx", crows)
            lrows = [r for r in self._rows("letture.xlsx") if _i(r[2]) != pid]
            self._overwrite("letture.xlsx", lrows)

    # ── COMMENTS ──────────────────────────────────────

    def _row_to_comment(self, r) -> Comment:
        return Comment(
            id=_i(r[0]), problem_id=_i(r[1]), autore=_s(r[2]),
            role=_s(r[3]) or "user", testo=_s(r[4]),
            data_ora=_dt(r[5]) or datetime.utcnow(),
        )

    def _comment_to_row(self, c: Comment) -> tuple:
        return (c.id, c.problem_id, c.autore, c.role, c.testo, _fmt_dt(c.data_ora))

    def get_comments_grouped(self) -> Dict[int, List[Comment]]:
        """
        Tutti i commenti raggruppati per ticket, con UNA sola lettura del file.

        Serve alla dashboard, che prima chiamava get_comments() dentro un ciclo
        e quindi rileggeva l'intero commenti.xlsx una volta per ogni ticket:
        con 60 ticket aperti e un anno di archivio erano ~15 secondi di attesa.
        """
        with _lock:
            gruppi: Dict[int, List[Comment]] = {}
            for r in self._rows("commenti.xlsx"):
                pid = _i(r[1])
                gruppi.setdefault(pid, []).append(self._row_to_comment(r))
        for lista in gruppi.values():
            lista.sort(key=lambda c: c.data_ora or datetime.min)
        return gruppi

    def get_comments(self, problem_id: int) -> List[Comment]:
        with _lock:
            rows = [r for r in self._rows("commenti.xlsx") if _i(r[1]) == problem_id]
            comments = [self._row_to_comment(r) for r in rows]
            return sorted(comments, key=lambda c: c.data_ora or datetime.min)

    def add_comment(self, problem_id: int, autore: str, role: str, testo: str) -> Comment:
        with _lock:
            rows = self._rows("commenti.xlsx")
            new_id = _next_id(rows)
            c = Comment(id=new_id, problem_id=problem_id, autore=autore,
                        role=role, testo=testo, data_ora=datetime.utcnow())
            rows.append(self._comment_to_row(c))
            self._overwrite("commenti.xlsx", rows)
            return c

    # ── CINEMAS ───────────────────────────────────────

    def _row_to_cinema(self, r) -> Cinema:
        return Cinema(
            id=_i(r[0]), nome=_s(r[1]), città=_s(r[2]),
            num_sale=_i(r[3], 1), telefono=_s(r[4]),
            indirizzo=_s(r[5]), lat=_f(r[6]), lng=_f(r[7]),
        )

    def _cinema_to_row(self, c: Cinema) -> tuple:
        return (c.id, c.nome, c.città, c.num_sale, c.telefono,
                c.indirizzo, c.lat or "", c.lng or "")

    def get_all_cinemas(self, order_by: str = "nome") -> List[Cinema]:
        with _lock:
            cinemas = [self._row_to_cinema(r) for r in self._rows("cinema.xlsx")]
        if order_by == "città_nome":
            cinemas.sort(key=lambda c: (c.città, c.nome))
        else:
            cinemas.sort(key=lambda c: c.nome)
        return cinemas

    def get_cinema_by_id(self, cid: int) -> Optional[Cinema]:
        with _lock:
            for r in self._rows("cinema.xlsx"):
                if _i(r[0]) == cid:
                    return self._row_to_cinema(r)
        return None

    def get_cinemas_by_ids(self, ids: list) -> List[Cinema]:
        with _lock:
            return [self._row_to_cinema(r)
                    for r in self._rows("cinema.xlsx") if _i(r[0]) in ids]

    def get_cinema_by_nome(self, nome: str) -> Optional[Cinema]:
        with _lock:
            for r in self._rows("cinema.xlsx"):
                if _s(r[1]) == nome:
                    return self._row_to_cinema(r)
        return None

    def create_cinema(self, nome: str, città: str, num_sale: int = 1,
                      telefono: str = "", indirizzo: str = "",
                      lat=None, lng=None) -> Cinema:
        with _lock:
            rows = self._rows("cinema.xlsx")
            new_id = _next_id(rows)
            c = Cinema(id=new_id, nome=nome, città=città, num_sale=num_sale,
                       telefono=telefono, indirizzo=indirizzo, lat=lat, lng=lng)
            rows.append(self._cinema_to_row(c))
            self._overwrite("cinema.xlsx", rows)
            return c

    def sostituisci_cinema(self, elenco: List[dict]) -> List[Cinema]:
        """
        Rimpiazza in un colpo solo l'intera anagrafica cinema.

        Farlo cancellando e ricreando uno per uno significava riscrivere lo
        stesso file Excel piu' di quattrocento volte di seguito: su Windows
        bastava che l'antivirus o Excel toccassero il file in uno di quei
        momenti per far fallire tutto con "Accesso negato".

        Qui il file viene scritto una volta sola. Le assegnazioni degli
        utenti non vengono toccate: se ne occupa chi chiama, che sa come
        ricollegarle.
        """
        with _lock:
            creati = []
            righe = []
            for i, c in enumerate(elenco, start=1):
                cin = Cinema(id=i, nome=c.get("nome", ""),
                             città=c.get("città", ""),
                             num_sale=_i(c.get("num_sale"), 1) or 1,
                             telefono=c.get("telefono", "") or "",
                             indirizzo=c.get("indirizzo", "") or "",
                             lat=c.get("lat"), lng=c.get("lng"))
                righe.append(self._cinema_to_row(cin))
                creati.append(cin)
            self._overwrite("cinema.xlsx", righe)

            # Le vecchie assegnazioni puntano a identificativi che non
            # esistono piu': si azzerano qui e le rimette chi importa.
            self._overwrite("assegnazioni.xlsx", [])
            return creati

    def update_cinema(self, c: Cinema):
        with _lock:
            rows = self._rows("cinema.xlsx")
            rows = [self._cinema_to_row(c) if _i(r[0]) == c.id else r for r in rows]
            self._overwrite("cinema.xlsx", rows)

    def delete_cinema(self, cid: int):
        with _lock:
            cinema = None
            for r in self._rows("cinema.xlsx"):
                if _i(r[0]) == cid:
                    cinema = self._row_to_cinema(r)
                    break
            rows = [r for r in self._rows("cinema.xlsx") if _i(r[0]) != cid]
            self._overwrite("cinema.xlsx", rows)
            if cinema:
                self._add_deleted_cinema(cinema.nome)
            # rimuovi assegnazioni
            arows = [r for r in self._rows("assegnazioni.xlsx") if _i(r[2]) != cid]
            self._overwrite("assegnazioni.xlsx", arows)

    def get_all_cinema_nomi(self) -> set:
        with _lock:
            return {_s(r[1]) for r in self._rows("cinema.xlsx")}

    # ── CINEMA ELIMINATI ──────────────────────────────

    def _add_deleted_cinema(self, nome: str):
        rows = self._rows("cinema_eliminati.xlsx")
        if not any(_s(r[1]) == nome for r in rows):
            new_id = _next_id(rows)
            rows.append((new_id, nome))
            self._overwrite("cinema_eliminati.xlsx", rows)

    def get_deleted_cinema_nomi(self) -> set:
        with _lock:
            return {_s(r[1]) for r in self._rows("cinema_eliminati.xlsx")}

    # ── TICKET READS ──────────────────────────────────

    def _row_to_ticketread(self, r) -> TicketRead:
        return TicketRead(
            id=_i(r[0]), user_id=_i(r[1]), problem_id=_i(r[2]),
            last_read_at=_dt(r[3]),
        )

    def _tr_to_row(self, tr: TicketRead) -> tuple:
        return (tr.id, tr.user_id, tr.problem_id, _fmt_dt(tr.last_read_at))

    def get_reads_by_user(self, user_id: int) -> Dict[int, datetime]:
        """Restituisce {problem_id: last_read_at} per l'utente."""
        with _lock:
            result = {}
            for r in self._rows("letture.xlsx"):
                if _i(r[1]) == user_id:
                    result[_i(r[2])] = _dt(r[3])
            return result

    def upsert_ticket_read(self, user_id: int, problem_id: int):
        with _lock:
            rows = self._rows("letture.xlsx")
            now_str = _fmt_dt(datetime.utcnow())
            found = False
            new_rows = []
            for r in rows:
                if _i(r[1]) == user_id and _i(r[2]) == problem_id:
                    new_rows.append((r[0], user_id, problem_id, now_str))
                    found = True
                else:
                    new_rows.append(r)
            if not found:
                new_id = _next_id(rows)
                new_rows.append((new_id, user_id, problem_id, now_str))
            self._overwrite("letture.xlsx", new_rows)

    # ── USER-CINEMA ASSIGNMENTS ────────────────────────

    def get_cinema_ids_for_user(self, user_id: int) -> List[int]:
        with _lock:
            return [_i(r[2]) for r in self._rows("assegnazioni.xlsx")
                    if _i(r[1]) == user_id]

    def set_user_cinemas(self, user_id: int, cinema_ids: List[int]):
        with _lock:
            rows = [r for r in self._rows("assegnazioni.xlsx") if _i(r[1]) != user_id]
            base_id = _next_id(rows) if rows else 1
            for i, cid in enumerate(cinema_ids):
                rows.append((base_id + i, user_id, cid))
            self._overwrite("assegnazioni.xlsx", rows)

    # ── SEED ──────────────────────────────────────────

    def _migra_colonna_password_chiara(self):
        """
        Assicura che utenti.xlsx abbia la colonna 'password_plain'.

        La colonna era stata tolta e va ripristinata su chi ha gia' il file
        senza. I valori restano vuoti: le password di prima erano state
        cancellate e dall'hash non si ricavano, quindi ricompariranno solo
        per chi riceve una password nuova.
        """
        percorso = _path("utenti.xlsx")
        if not os.path.exists(percorso):
            return
        try:
            wb = openpyxl.load_workbook(percorso)
            ws = wb.active
            intestazione = [_s(c) for c in next(ws.iter_rows(values_only=True), ())]
        except Exception as e:
            print(f"[migrazione] utenti.xlsx non leggibile: {e}")
            return

        if "password_plain" in intestazione:
            return   # gia' a posto

        righe = []
        for r in list(ws.iter_rows(min_row=2, values_only=True)):
            if not r or r[0] is None:
                continue
            # id, username, hash | <qui> | role, telefono, email
            righe.append(tuple(r[:3]) + ("",) + tuple(r[3:]))

        self._overwrite("utenti.xlsx", righe)
        print(f"[migrazione] Ripristinata la colonna password in utenti.xlsx "
              f"({len(righe)} utenti, valori da riempire)")

    def _migra_colonna_stato(self):
        """
        Aggiunge la colonna 'stato' a utenti.xlsx se manca.

        Serve a distinguere chi si e' registrato da solo e aspetta la
        password ("richiesta") da chi puo' gia' entrare ("attivo"). Chi
        c'era prima della registrazione libera e' ovviamente gia' attivo.
        """
        percorso = _path("utenti.xlsx")
        if not os.path.exists(percorso):
            return
        try:
            wb = openpyxl.load_workbook(percorso)
            ws = wb.active
            intestazione = [_s(c) for c in next(ws.iter_rows(values_only=True), ())]
        except Exception as e:
            print(f"[migrazione] utenti.xlsx non leggibile: {e}")
            return

        if "stato" in intestazione:
            return   # gia' a posto

        righe = []
        for r in list(ws.iter_rows(min_row=2, values_only=True)):
            if not r or r[0] is None:
                continue
            righe.append(tuple(r[:7]) + ("attivo",))

        self._overwrite("utenti.xlsx", righe)
        print(f"[migrazione] Aggiunta la colonna stato in utenti.xlsx "
              f"({len(righe)} utenti, tutti attivi)")

    def utenti_in_attesa(self) -> List[User]:
        """Chi si e' registrato da solo e aspetta ancora la password."""
        return [u for u in self.get_all_users() if u.stato == "richiesta"]

    def seed(self):
        """Inizializza i file e inserisce dati di default se mancanti."""
        _ensure_dir()
        # Assicura che tutti i file esistano
        for fname, headers in self.HEADERS.items():
            if not os.path.exists(_path(fname)):
                _load_wb(fname, headers)

        # Migrazioni sui file già esistenti (prima di qualsiasi lettura)
        self._migra_colonna_password_chiara()
        self._migra_colonna_stato()

        # Admin di default
        if not self.get_user_by_username("admin"):
            self.create_user(
                username="admin",
                password_hash=generate_password_hash("admin1234"),
                password_plain="admin1234",
                role="admin",
            )
            print("✅ Utente admin creato (admin / admin1234)")
            print("   ⚠  Cambia subito questa password dalla pagina Utenti.")

        # NOTA: qui c'era un elenco di 41 cinema di esempio, reinserito a
        # ogni avvio. Erano nomi inventati ("Cinema Firenze", "Cinema Empoli")
        # che non corrispondono a locali reali e sporcavano l'anagrafica.
        # I cinema veri si caricano dal Support Tool con importa_cinema.py
        # oppure dal pulsante nella pagina Cinema del sito.

    # ── IMPORT da Excel esterno ────────────────────────

    def import_from_workbook(self, wb) -> dict:
        """
        Importa ticket e cinema da un workbook openpyxl caricato dall'utente.
        Restituisce contatori: added_problems, skipped_problems, added_cinemas, skipped_cinemas.
        """
        added_problems = 0
        skipped_problems = 0
        added_cinemas = 0
        skipped_cinemas = 0

        existing_ids = {p.id for p in self.get_all_problems()}
        existing_nomi = self.get_all_cinema_nomi()

        def _val(v):
            return str(v).strip() if v is not None else ""

        def _parse_dt_imp(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val
            return _dt(val)

        for sheet_name in ["Ticket Aperti", "Archivio Chiusi"]:
            ws = wb[sheet_name] if sheet_name in wb.sheetnames else None
            if not ws:
                continue
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2:
                continue
            for row in rows[1:]:
                if not any(row):
                    continue
                try:
                    row_id  = int(row[0]) if row[0] else None
                    cinema  = _val(row[1])
                    città   = _val(row[2])
                    sala    = _val(row[3]) or "1"
                    tipo    = _val(row[4])
                    urgenza = _val(row[5]) or "Non urgente"
                    autore  = _val(row[7]) if len(row) > 7 else "import"
                    data_ora = _parse_dt_imp(row[8]) if len(row) > 8 else None
                    stato   = _val(row[6]) if sheet_name == "Ticket Aperti" else "Chiuso"
                    chiuso_da = _val(row[9]) if len(row) > 9 else None
                    chiuso_il = _parse_dt_imp(row[10]) if len(row) > 10 else None
                except Exception:
                    continue
                if not cinema or not tipo:
                    continue
                if row_id and row_id in existing_ids:
                    skipped_problems += 1
                    continue
                p = self.create_problem(cinema=cinema, città=città, sala=sala,
                                        tipo=tipo, urgenza=urgenza, stato=stato, autore=autore)
                if data_ora:
                    p.data_ora = data_ora
                p.chiuso_da = chiuso_da or None
                p.chiuso_il = chiuso_il
                self.update_problem(p)
                if row_id:
                    existing_ids.add(row_id)
                added_problems += 1

        if "Cinema" in wb.sheetnames:
            ws = wb["Cinema"]
            rows = list(ws.iter_rows(values_only=True))
            for row in rows[1:]:
                if not any(row):
                    continue
                try:
                    nome     = _val(row[1])
                    città    = _val(row[2])
                    num_sale = int(row[3]) if row[3] else 1
                    telefono = _val(row[4])
                    indirizzo = _val(row[5])
                    lat = _f(row[6])
                    lng = _f(row[7])
                except Exception:
                    continue
                if not nome:
                    continue
                if nome in existing_nomi:
                    skipped_cinemas += 1
                    continue
                self.create_cinema(nome=nome, città=città, num_sale=num_sale,
                                   telefono=telefono, indirizzo=indirizzo, lat=lat, lng=lng)
                existing_nomi.add(nome)
                added_cinemas += 1

        return {
            "added_problems": added_problems,
            "skipped_problems": skipped_problems,
            "added_cinemas": added_cinemas,
            "skipped_cinemas": skipped_cinemas,
        }


# ── Istanza globale ───────────────────────────────────
store = ExcelStore()
