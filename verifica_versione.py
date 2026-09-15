"""
Dice se il sito sta girando il codice aggiornato e se i file dati
sono scrivibili.

Da eseguire sul PC dove gira il sito:

    python verifica_versione.py
"""
import os
import sys
import tempfile

CARTELLA = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(CARTELLA, "data")


def controlla_codice() -> bool:
    """Le correzioni recenti ci sono? Si riconoscono da come e' scritto il codice."""
    print("1) Versione del codice\n")
    attese = [
        ("storage.py", "sostituisci_cinema",
         "importazione con una sola scrittura"),
        ("storage.py", "il file risulta occupato",
         "messaggio comprensibile se il file e' bloccato"),
        ("importa_cinema.py", "SIGRA_RAW",
         "lettura del nuovo formato del Support Tool"),
    ]
    tutto_ok = True
    for nome_file, spia, descrizione in attese:
        percorso = os.path.join(CARTELLA, nome_file)
        try:
            with open(percorso, encoding="utf-8") as f:
                presente = spia in f.read()
        except OSError:
            presente = False
        print(f"   [{'OK' if presente else 'MANCA'}] {descrizione}")
        tutto_ok = tutto_ok and presente

    print()
    if tutto_ok:
        print("   Il codice e' aggiornato.")
    else:
        print("   IL CODICE E' VECCHIO. Sul PC del server esegui:")
        print("       git pull")
        print("   poi CHIUDI e RIAVVIA il sito: Python carica i file")
        print("   all'avvio, quindi finche' il processo e' quello di prima")
        print("   continua a usare il codice vecchio.")
    return tutto_ok


def controlla_scrittura() -> bool:
    """I file dati sono davvero scrivibili adesso?"""
    print("\n2) Accesso ai file dati\n")
    if not os.path.isdir(DATA):
        print(f"   La cartella {DATA} non esiste.")
        return False

    tutto_ok = True
    for nome in sorted(os.listdir(DATA)):
        if not nome.endswith(".xlsx"):
            continue
        percorso = os.path.join(DATA, nome)
        try:
            # Stessa operazione che fa il sito: scrive un temporaneo e lo
            # rinomina al posto dell'originale.
            fd, tmp = tempfile.mkstemp(dir=DATA, prefix=".prova.", suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                with open(percorso, "rb") as orig:
                    f.write(orig.read())
            os.replace(tmp, percorso)
            print(f"   [OK]    {nome}")
        except PermissionError:
            print(f"   [BLOCCATO] {nome}  <-- qualcuno lo tiene aperto")
            tutto_ok = False
            try:
                os.remove(tmp)
            except OSError:
                pass
        except Exception as e:
            print(f"   [ERRORE] {nome}: {type(e).__name__}")
            tutto_ok = False
            try:
                os.remove(tmp)
            except OSError:
                pass

    if not tutto_ok:
        print("""
   Qualcosa tiene aperti i file. Le cause piu' frequenti:

     1. Il file e' aperto in Excel. Chiudi Excel del tutto.

     2. La cartella e' dentro OneDrive, Google Drive o Dropbox:
        il programma di sincronizzazione tiene i file aperti.
        Sposta la cartella del sito fuori da li'.

     3. L'antivirus scansiona la cartella. Aggiungi data alle
        esclusioni.

     4. Il sito e' avviato due volte. Apri Gestione attivita' e
        controlla se ci sono piu' processi pythonw.exe: chiudili
        tutti e riavvia una volta sola.
""")
    return tutto_ok


def main() -> int:
    print("=== Verifica installazione — SigraFilm NOC ===\n")
    print(f"Cartella: {CARTELLA}\n")
    a = controlla_codice()
    b = controlla_scrittura()
    print("\n" + "=" * 52)
    if a and b:
        print("\nTutto a posto: l'importazione dovrebbe funzionare.")
        return 0
    print("\nRisolvi i punti segnalati qui sopra, poi riprova.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
