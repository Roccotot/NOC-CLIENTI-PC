# Guida all'aggiornamento

Questo aggiornamento tocca **sicurezza, dati e prestazioni**. Segui i passaggi
nell'ordine indicato: il primo è importante e non va saltato.

---

## ⚠️ 1. Prima di tutto: metti al sicuro il database

I file Excel in `data/` non sono più versionati (prima lo erano, ed era un
rischio: un deploy poteva riportare il database indietro di mesi).

Proprio per questo, **prima di scaricare l'aggiornamento fai una copia della
cartella `data/`**:

```bat
xcopy data data_backup_PRIMA_AGGIORNAMENTO\ /E /I
```

Se durante il `git pull` compare un errore del tipo
*"Your local changes would be overwritten"* riferito a `data/`, è previsto:
significa che git sta cercando di togliere dal versionamento file che tu hai
modificato. Risolvi così, senza perdere niente:

```bat
git rm -r --cached data
git pull
```

I file restano sul disco: cambia solo che git smette di tracciarli.

---

## 2. Scarica l'aggiornamento

```bat
git pull
```

## 3. Installa la libreria per i PDF

Serve per il pulsante 📦 delle etichette di spedizione:

```bat
C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pip install reportlab
```

## 4. Riavvia il sito

Chiudi e riavvia con `start_noc.bat`. Al primo avvio vedrai:

```
[chiave] Generata una nuova SECRET_KEY in .secret_key
[migrazione] Rimosse N password in chiaro da utenti.xlsx
```

Sono entrambi messaggi normali e appaiono una sola volta.

> **Nota:** tutti gli utenti dovranno rifare il login, perché la chiave che
> firma le sessioni è cambiata. Le password restano quelle di prima.

---

## Cosa è cambiato

### Sicurezza

| Prima | Adesso |
|---|---|
| L'indirizzo `/reset-admin-password-7x9k` era raggiungibile **da chiunque su internet senza password** e dava il controllo del sito | Route rimossa. Per il reset d'emergenza: `python reset_admin.py` dal PC del server |
| Le password erano salvate **in chiaro** e mostrate nella pagina Utenti | Colonna eliminata e contenuto cancellato dal disco. Restano solo gli hash |
| Chiave di sessione con valore predefinito noto | Chiave casuale salvata in `.secret_key`, fuori da git |
| I form erano vulnerabili a CSRF | Tutti i 21 form protetti da gettone |

**Se ti serve reimpostare la password di un amministratore**, dal PC del server:

```bat
python reset_admin.py
```

Chiede la nuova password a schermo, senza lasciarla nella cronologia dei comandi.

### Protezione dei dati

- **Salvataggio atomico**: prima un'interruzione a metà scrittura (PC spento,
  processo terminato) lasciava il file troncato e i dati persi. Ora si scrive su
  file temporaneo e si rinomina solo a fine scrittura.
- **Backup automatici** in `data/backup/`: fino a 10 copie per file, al massimo
  una all'ora. Per ripristinare, copia il file scelto sopra quello in `data/`
  (a sito spento).

### Prestazioni

La dashboard rileggeva l'intero archivio messaggi **una volta per ogni ticket**.
Con 500 ticket e 3000 messaggi erano ~17 secondi di attesa: ora sono 0,3.

### Funzionalità

- **Visibilità per cinema**: chi lavora nello stesso cinema vede gli stessi
  ticket. Prima ognuno vedeva solo quelli aperti da sé, anche a parità di cinema
  assegnato.
- **Ricerca** in dashboard e archivio: cinema, città, sala, descrizione, autore,
  numero ticket (`#12`).
- **Archivio paginato** a 50 ticket per pagina.
- **Notifica al cliente** quando l'assistenza risponde (serve l'email
  nell'anagrafica utente).

---

## Notifiche email

Per attivarle serve il file `.env` nella cartella del progetto. Copia
`.env.example` in `.env` e compila con i dati veri della casella:

```
SMTP_HOST=...
SMTP_PORT=465
SMTP_SSL=1
SMTP_USER=assistenza@sigrafilm.it
SMTP_PASSWORD=...
NOTIFY_EMAIL=assistenza@sigrafilm.it
APP_BASE_URL=http://188.8.192.138:5000
```

Il file `.env` non finisce su GitHub, quindi la password resta solo sul tuo PC.

Senza `.env` il sito funziona normalmente: le notifiche vengono solo saltate.
