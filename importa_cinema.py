"""
Sostituisce l'anagrafica cinema con quella reale del Support Tool.

Da eseguire sul PC dove gira il sito:

    python importa_cinema.py

Scarica l'elenco da https://roccotot.github.io/Support-Tool/, mostra cosa
cambierebbe e chiede conferma prima di scrivere qualsiasi cosa.

Le assegnazioni utente-cinema vengono ricollegate automaticamente anche
quando il nome cambia leggermente ("Cinema Excelsior" -> "Excelsior"),
perché puntano all'identificativo del cinema e non al nome.
"""
import re
import sys
import unicodedata
import urllib.request

from storage import store

# Il Support Tool teneva gli elenchi dentro index.html; da settembre 2026
# stanno in dati.js come SIGRA_RAW = { vpn: `...`, offline: `...`, estivi: `...` }.
# Proviamo prima il file nuovo, poi la pagina, cosi' funziona con entrambi.
FONTI = [
    "https://roccotot.github.io/Support-Tool/dati.js",
    "https://raw.githubusercontent.com/Roccotot/Support-Tool/main/dati.js",
    "https://roccotot.github.io/Support-Tool/",
    "https://raw.githubusercontent.com/Roccotot/Support-Tool/main/index.html",
]

# Nomi degli elenchi nelle due versioni: quelli nuovi (dentro SIGRA_RAW)
# e quelli vecchi (variabili a se stanti in index.html).
ELENCHI = ["vpn", "offline", "estivi", "RAW", "RAW_ESTIVI", "RAW_NOVPN"]
TIMEOUT = 30

# Parole generiche da ignorare nel confronto dei nomi: servono a
# riconoscere lo stesso locale quando cambia la dicitura, per esempio
# "Cinema Excelsior" / "Excelsior" oppure "Museo Pecci" / "Centro Pecci".
#
# "arena" ed "estiva" NON vanno qui: distinguono l'arena estiva dal cinema
# al chiuso della stessa citta' (a Arezzo esistono sia "Eden" sia "Arena
# Estiva Eden", e sono due locali diversi).
RUMORE = {"cinema", "teatro", "multisala", "sala",
          "centro", "museo", "circolo", "spazio", "casa",
          "nuovo", "nuova", "il", "la", "lo"}


def normalizza(testo) -> str:
    testo = unicodedata.normalize("NFKD", str(testo or "").lower())
    return re.sub(r"[^a-z0-9]", "", testo)


def chiave_confronto(nome, citta) -> str:
    """Chiave che ignora le parole generiche, per riconoscere lo stesso cinema."""
    parole = [p for p in re.split(r"[^\w]+", str(nome or "").lower())
              if p and p not in RUMORE]
    return normalizza(" ".join(parole)) + "|" + normalizza(citta)


def scarica() -> str:
    """
    Scarica la sorgente dati, provando gli indirizzi in ordine.

    Si accontenta del primo che contenga davvero degli elenchi: un indirizzo
    puo' rispondere (pagina di errore, versione senza dati) senza contenere
    nulla di utile, e in quel caso va provato il successivo.
    """
    ultimo_errore = None
    for url in FONTI:
        try:
            richiesta = urllib.request.Request(
                url, headers={"User-Agent": "SigraFilmNOC/1.0"})
            with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as r:
                testo = r.read().decode("utf-8", errors="replace")
            if estrai(testo):
                return testo
            ultimo_errore = f"{url} non contiene elenchi di cinema"
        except Exception as e:
            ultimo_errore = f"{url}: {type(e).__name__}"
    raise RuntimeError(f"Impossibile scaricare l'elenco ({ultimo_errore})")


def estrai(html: str) -> list:
    """Ricava nome, città, numero sale e coordinate di ogni cinema."""
    trovati = {}
    for nome_elenco in ELENCHI:
        m = re.search(rf"\b{nome_elenco}\s*[:=]\s*`(.*?)`", html, re.S)
        if not m:
            continue
        for riga in m.group(1).strip().split("\n"):
            riga = riga.strip()
            if not riga:
                continue
            colonne = riga.split("\t")
            parti = colonne[0].split(" - ")
            if len(parti) < 2:
                continue
            nome = parti[0].strip()
            citta = re.sub(r"\s*-\s*[A-Z]{2}$", "", parti[1].strip()).strip()
            sezione = parti[2].strip() if len(parti) > 2 else ""

            c = trovati.setdefault((nome, citta), {
                "nome": nome, "città": citta, "sale": set(),
                "lat": None, "lng": None})

            if sezione.lower() == "coord" and len(colonne) > 1:
                try:
                    la, ln = colonne[1].split(",")
                    c["lat"] = round(float(la), 6)
                    c["lng"] = round(float(ln), 6)
                except Exception:
                    pass

            sala = re.match(r"Sala\s+0*(\d+)", sezione, re.I)
            if sala:
                c["sale"].add(int(sala.group(1)))

    elenco = [{"nome": c["nome"], "città": c["città"],
               "num_sale": max(c["sale"]) if c["sale"] else 1,
               "lat": c["lat"], "lng": c["lng"]}
              for c in trovati.values()]
    elenco.sort(key=lambda x: (x["città"], x["nome"]))
    return elenco


def importa(store) -> dict:
    """
    Sostituisce l'anagrafica con i cinema del Support Tool.

    Usata sia dallo script da riga di comando sia dal pulsante nella pagina
    Cinema del sito, cosi' la logica sta in un posto solo.

    Le assegnazioni utente-cinema puntano all'identificativo, non al nome:
    cancellare i cinema le romperebbe, quindi vengono ricollegate
    riconoscendo lo stesso locale anche se il nome cambia leggermente.
    """
    nuovi = estrai(scarica())
    if not nuovi:
        raise RuntimeError("nessun cinema trovato nella pagina scaricata; "
                           "forse il formato del Support Tool e' cambiato")

    attuali = store.get_all_cinemas()
    utenti = store.get_all_users()

    # Chi era assegnato a cosa, per nome: gli identificativi cambiano
    assegnazioni = {}
    for u in utenti:
        ids = set(store.get_cinema_ids_for_user(u.id))
        chiavi = [chiave_confronto(c.nome, c.città) for c in attuali if c.id in ids]
        if chiavi:
            assegnazioni[u.id] = chiavi

    for c in attuali:
        store.delete_cinema(c.id)

    mappa = {}
    for c in nuovi:
        creato = store.create_cinema(nome=c["nome"], città=c["città"],
                                     num_sale=c["num_sale"],
                                     lat=c["lat"], lng=c["lng"])
        mappa[chiave_confronto(c["nome"], c["città"])] = creato.id

    ricollegate = perse = 0
    for user_id, chiavi in assegnazioni.items():
        nuovi_id = [mappa[k] for k in chiavi if k in mappa]
        perse += len(chiavi) - len(nuovi_id)
        ricollegate += len(nuovi_id)
        store.set_user_cinemas(user_id, nuovi_id)

    return {"inseriti": len(nuovi), "ricollegate": ricollegate, "perse": perse}


def main() -> int:
    print("=== Importazione cinema dal Support Tool ===\n")

    print("1) Scarico l'elenco...")
    try:
        html = scarica()
    except Exception as e:
        print(f"\nERRORE: {e}")
        print("\nControlla che il PC abbia la connessione a internet.")
        return 1

    nuovi = estrai(html)
    if not nuovi:
        print("\nERRORE: nessun cinema trovato nella pagina scaricata.")
        print("Forse il formato del Support Tool e' cambiato.")
        return 1
    print(f"   Trovati {len(nuovi)} cinema "
          f"({sum(1 for c in nuovi if c['lat'])} con coordinate)\n")

    # Fotografia della situazione attuale
    attuali = store.get_all_cinemas()
    utenti = store.get_all_users()
    assegnazioni = {u.id: set(store.get_cinema_ids_for_user(u.id)) for u in utenti}
    ticket_per_cinema = {}
    for p in store.get_all_problems():
        ticket_per_cinema.setdefault(normalizza(p.cinema), []).append(p.id)

    indice_nuovi = {chiave_confronto(c["nome"], c["città"]): c for c in nuovi}

    print("2) Confronto con l'anagrafica attuale")
    print(f"   Cinema attuali: {len(attuali)}  ->  nuovi: {len(nuovi)}\n")

    orfani = []
    for c in attuali:
        k = chiave_confronto(c.nome, c.città)
        if k in indice_nuovi:
            continue
        chi = [u.username for u in utenti if c.id in assegnazioni.get(u.id, set())]
        tk = ticket_per_cinema.get(normalizza(c.nome), [])
        if chi or tk:
            orfani.append((c, chi, tk))

    if orfani:
        print("   ATTENZIONE — questi cinema hanno utenti o ticket collegati")
        print("   ma NON compaiono nel Support Tool:\n")
        for c, chi, tk in orfani:
            print(f"      {c.nome} ({c.città})")
            if chi:
                print(f"         utenti assegnati: {', '.join(chi)}")
            if tk:
                print(f"         ticket: {', '.join('#'+str(t) for t in tk)}")
        print("\n   I loro ticket restano leggibili (il nome del cinema e'")
        print("   scritto dentro il ticket), ma gli utenti perderanno")
        print("   l'assegnazione e non vedranno piu' i ticket del cinema.\n")

    print("   I cinema riconosciuti manterranno le assegnazioni utente,")
    print("   anche se il nome cambia leggermente.\n")

    risposta = input(f"Sostituire i {len(attuali)} cinema attuali con i "
                     f"{len(nuovi)} del Support Tool? (scrivi SI) ").strip()
    if risposta.upper() not in ("SI", "SÌ"):
        print("\nAnnullato: nessuna modifica.")
        return 0

    # Chi era assegnato a cosa, per nome (gli id cambiano)
    assegnazioni_per_nome = {}
    for u in utenti:
        nomi = []
        for c in attuali:
            if c.id in assegnazioni.get(u.id, set()):
                nomi.append(chiave_confronto(c.nome, c.città))
        if nomi:
            assegnazioni_per_nome[u.id] = nomi

    print("\n3) Sostituisco l'anagrafica...")
    for c in attuali:
        store.delete_cinema(c.id)

    mappa_nuovi = {}
    for c in nuovi:
        creato = store.create_cinema(nome=c["nome"], città=c["città"],
                                     num_sale=c["num_sale"],
                                     lat=c["lat"], lng=c["lng"])
        mappa_nuovi[chiave_confronto(c["nome"], c["città"])] = creato.id
    print(f"   Inseriti {len(nuovi)} cinema")

    print("\n4) Ricollego le assegnazioni utente...")
    ricollegati = persi = 0
    for user_id, chiavi in assegnazioni_per_nome.items():
        nuovi_id = [mappa_nuovi[k] for k in chiavi if k in mappa_nuovi]
        persi += len(chiavi) - len(nuovi_id)
        ricollegati += len(nuovi_id)
        store.set_user_cinemas(user_id, nuovi_id)
    print(f"   Assegnazioni ricollegate: {ricollegati}")
    if persi:
        print(f"   Assegnazioni perse (cinema non piu' presente): {persi}")

    print("\nFatto. Ricarica la pagina Cinema del sito per vedere l'elenco.")
    print("Se qualche utente ha perso l'assegnazione, riassegnala dalla")
    print("pagina Utenti con il pulsante 🎬.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
