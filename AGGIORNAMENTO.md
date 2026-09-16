# Come aggiornare il sito senza perdere niente

## In due righe

Scompatta lo ZIP sopra la cartella del sito e **sovrascrivi tutto quello che
ti chiede**. Non c'è niente dentro lo ZIP che possa cancellare i tuoi dati:
le cartelle `data/` e `allegati/` e il file `.secret_key` non ci sono proprio.

---

## 1. Ferma il sito

Se il sito è già acceso con l'icona vicino all'orologio: tasto destro
sull'icona → **Ferma il sito ed esci**. Altrimenti chiudi la finestra nera
di `start_noc.bat`.

Se resta acceso, Windows tiene i file Excel occupati e il salvataggio può
dare *"Accesso negato"*.

## 2. Fai una copia dei dati

Un minuto, e dormi tranquillo:

```bat
xcopy data data_backup\ /E /I /Y
xcopy allegati allegati_backup\ /E /I /Y
```

## 3. Scompatta lo ZIP sopra la cartella del sito

Quando Windows chiede se sostituire i file, rispondi **sì a tutto**.

## 4. Riavvia con `start_noc.bat`

Al primo avvio dopo l'aggiornamento vedrai una riga come questa:

```
[migrazione] utenti.xlsx: aggiunte le colonne stato, nome (5 utenti)
```

È normale e compare una volta sola: il file degli utenti prende due colonne
nuove. Tutti gli utenti che hai già risultano attivi e continuano a entrare
con la password di sempre.

---

## Cosa NON viene toccato

Queste cose stanno solo sul tuo PC e nello ZIP non ci sono:

| Cosa | Dove |
|---|---|
| Ticket, cinema, utenti, messaggi | `data\*.xlsx` |
| Backup automatici | `data\backup\` |
| Impostazioni email (password compresa) | `data\impostazioni.json` |
| Foto e video allegati ai ticket | `allegati\` |
| Chiave delle sessioni | `.secret_key` |

Se per sbaglio cancelli `.secret_key` non perdi dati: il sito ne genera una
nuova e tutti devono solo rifare il login.

---

## Cosa c'è di nuovo

### Icona vicino all'orologio

Avviando il sito con `start_noc.bat` (o `start_noc.vbs`) compare un pallino
rosso con la **S** in basso a destra, vicino all'orologio. Da lì:

- **doppio clic** apre il sito nel browser
- **tasto destro → Ferma il sito ed esci** lo spegne, con una domanda di
  conferma prima. Niente più Gestione attività
- passando il mouse sopra, vedi l'indirizzo da dare agli altri PC

> **Se non la vedi:** Windows 11 nasconde le icone nuove. Premi la freccetta
> **^** accanto all'orologio: l'icona è lì dentro. Per tenerla sempre in
> vista trascinala fuori, oppure vai in *Impostazioni → Personalizzazione →
> Barra delle applicazioni → Altre icone nell'area di notifica* e accendila.

Se provi ad avviare il sito due volte, la seconda te lo dice invece di
aprire un secondo processo che muore in silenzio.

### Registrazione dei clienti

Nella pagina di login c'è il pulsante **Registrati**. Il responsabile di un
cinema compila nome e cognome, sceglie il cinema che gestisce e lascia
telefono ed email.

Non entra subito: la sua richiesta arriva a te.

- ti arriva una **email** a `assistenza@sigrafilm.it`
- nella pagina **Utenti** compare in cima, con la scritta gialla
  *"Nuova richiesta"*
- premi **✉ Approva**: il sito genera la password, gliela manda per email e
  da quel momento può entrare
- premi **✕** per rifiutare

Il nome utente lo ricava dal nome: *Mario Rossi* diventa `mario.rossi`.
Niente spazi né accenti, così è più difficile sbagliarlo da telefono.
Il nome per esteso resta scritto sotto, nella pagina Utenti.

### Dalla pagina di login è sparito WhatsApp

Al suo posto ci sono il pulsante Registrati e il link per scrivere alla
casella dell'assistenza.

### Su telefono le tabelle diventano schede

Ticket, archivio, utenti e cinema: sul telefono ogni riga diventa un
riquadro con le voci una sotto l'altra, invece di una tabella con le
colonne tagliate.

### Due cose che non funzionavano

- Nella pagina Utenti, su computer, il campo *"Nuova password"* e il
  pulsante di eliminazione finivano oltre il bordo e non si potevano
  cliccare. Ora la tabella si scorre di lato.
- Il dettaglio utente non mostrava più il ruolo (era un errore nel codice
  della pagina).

---

## Se qualcosa va storto

**Il sito non parte.** Apri `start_noc.bat` e leggi la finestra nera: l'ultima
riga dice cosa manca. Quasi sempre è una libreria:

```bat
python -m pip install -r requirements.txt
```

**Ho perso la password di admin.** Dal PC del sito:

```bat
python reset_admin.py
```

Chiede la nuova password a schermo, senza lasciarla scritta da nessuna parte.

**Voglio tornare indietro.** Rimetti a posto i dati dalla copia del passo 2:

```bat
xcopy data_backup data\ /E /I /Y
```

**Le notifiche email non partono.** Entra come amministratore e apri
**🔔 Notifiche** nel menu in alto: i campi sono già compilati con i dati
MC-link, serve solo la password della casella. Il pulsante
*Salva e invia una prova* dice esattamente cosa non va.
