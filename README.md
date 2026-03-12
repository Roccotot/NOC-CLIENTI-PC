# SigraFilm NOC Dashboard

Sistema interno di gestione dei problemi tecnici nei cinema **SigraFilm**.
Sviluppato con **Flask**, **PostgreSQL** e **Bootstrap 5**.

URL produzione: [sigrafilm.onrender.com](https://sigrafilm.onrender.com)

---

## Come funziona

### Accesso

Il sito richiede login. Esistono due ruoli:

| Ruolo | Cosa può fare |
|-------|--------------|
| **Admin** | Vede tutti i ticket di tutti gli utenti, gestisce cinema e utenti |
| **Utente** | Vede e gestisce solo i propri ticket; vede solo i cinema assegnatigli dall'admin |

L'utente `admin` viene creato automaticamente al primo avvio (password: `admin1234`).

---

### Ticket (Problemi tecnici)

Ogni ticket rappresenta un problema tecnico in una sala cinema. Contiene:

- **Cinema** e **Sala** — dove si è verificato il problema
- **Descrizione** — cosa è successo
- **Urgenza** — tre livelli: `Non urgente` / `Urgente` / `Critico`
- **Stato** — `Aperto` → `In corso` → `Chiuso`
- **Autore** e **data/ora** di apertura

#### Ciclo di vita di un ticket

```
Aperto → In corso → Chiuso → [Archivio]
```

1. L'utente apre un ticket dalla Dashboard scegliendo il cinema, la sala e descrivendo il problema.
2. Lo stato può essere aggiornato in qualsiasi momento dalla pagina di dettaglio del ticket.
3. Quando viene impostato su **Chiuso**, il sistema registra **chi lo ha chiuso** e **quando**.
4. I ticket chiusi spariscono dalla Dashboard e finiscono nell'**Archivio**.
5. Dall'archivio l'admin può **eliminare definitivamente** un ticket.

---

### Dashboard

La dashboard mostra tutti i ticket **non chiusi** con:

- **Statistiche** in cima: totale, aperti, in corso, critici
- **Filtri** per urgenza e stato
- **Tabella ordinabile** per ogni colonna
- **Badge chat** su ogni riga che indica quanti messaggi nuovi ci sono nel ticket
- Evidenziazione visiva per urgenza (Critico = rosso, Urgente = arancione)

---

### Dettaglio Ticket

Ogni ticket ha una pagina dedicata con:

- Informazioni complete (cinema, sala, descrizione, urgenza, stato, autore, data)
- **Chat interna** — commenti in stile messaggi tra utente e admin
- Possibilità di aggiornare stato e urgenza direttamente dalla pagina
- Badge "non letto" — la data di ultima lettura viene aggiornata ogni volta che si apre la pagina

---

### Archivio

Pagina `/closed` che mostra tutti i ticket chiusi con una colonna aggiuntiva:

> **Chiuso da** `nomeUtente` — `gg/mm/aaaa` alle `HH:MM`

I ticket chiusi prima dell'introduzione di questa funzione mostrano `—`.

---

### Gestione Cinema (solo Admin)

Pagina `/admin/cinemas` con:

- **Mappa interattiva** (CartoDB dark) che mostra tutti i cinema con coordinate
- Ogni marker mostra un popup con i ticket aperti per quel cinema
- Lista completa dei cinema con: città, nome, numero sale, telefono, indirizzo
- Possibilità di aggiungere, modificare ed eliminare cinema
- I cinema eliminati vengono registrati in una tabella `deleted_cinemas` per evitare che vengano reinseriti automaticamente dal seed

Al primo avvio il sistema inserisce automaticamente ~39 cinema SigraFilm in Toscana con indirizzi e coordinate.

---

### Gestione Utenti (solo Admin)

Pagina `/users` con:

- Lista di tutti gli utenti con ruolo, email, telefono
- Creazione nuovi utenti (username + password minimo 8 caratteri + ruolo)
- Reset password di un utente
- Eliminazione utenti (non si può eliminare se stessi o l'ultimo admin)
- **Assegnazione cinema**: ogni utente può essere limitato a vedere solo certi cinema. Se non ha cinema assegnati, vede tutti.

---

## Struttura del progetto

```
SigraFilm-NOC/
├── app.py                  # Backend Flask (routes, modelli, logica)
├── requirements.txt        # Dipendenze Python
├── templates/
│   ├── login.html
│   ├── dashboard.html      # Pagina principale con tabella ticket
│   ├── ticket_detail.html  # Dettaglio ticket + chat
│   ├── closed_tickets.html # Archivio ticket chiusi
│   ├── cinemas.html        # Mappa + lista cinema (admin)
│   ├── edit_cinema.html    # Modifica singolo cinema
│   ├── users.html          # Lista utenti (admin)
│   ├── user_detail.html    # Assegnazione cinema a utente
│   └── edit_problem.html   # Modifica ticket
└── static/
    ├── style.css           # Tema dark custom
    ├── logo_sigra.png
    └── favicon.svg
```

---

## Tecnologie

- [Flask](https://flask.palletsprojects.com/) — backend Python
- [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/) — ORM
- [PostgreSQL](https://www.postgresql.org/) — database (Neon.tech)
- [Bootstrap 5](https://getbootstrap.com/) — frontend responsive
- [Leaflet.js](https://leafletjs.com/) — mappa interattiva cinema
- [Gunicorn](https://gunicorn.org/) — application server
- [Render](https://render.com/) — hosting

---

## Variabili d'ambiente

| Variabile | Descrizione |
|-----------|-------------|
| `DATABASE_URL` | URL PostgreSQL (es. `postgresql://...`) |
| `SECRET_KEY` | Chiave segreta Flask per le sessioni |

Se `DATABASE_URL` non è impostata, usa SQLite locale (`app.db`) utile per sviluppo.

---

## Migrazioni DB

Non usa Alembic. Le colonne nuove vengono aggiunte automaticamente all'avvio tramite `ALTER TABLE` con gestione degli errori (se la colonna esiste già, viene ignorata silenziosamente).
