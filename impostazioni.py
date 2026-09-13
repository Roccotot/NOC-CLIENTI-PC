"""
Impostazioni modificabili dalla pagina web del portale.

Stanno in un file JSON separato (non in .env) perché devono poter essere
cambiate dall'interfaccia senza riavviare il sito: vengono rilette a ogni
utilizzo, non caricate una volta sola all'avvio.

Le variabili d'ambiente (.env) restano valide come valori di partenza: se
una chiave non è mai stata salvata dalla pagina, si usa quella dell'ambiente.
Così chi aveva già configurato il .env non perde niente.
"""
import json
import os
import tempfile
import threading

from config import carica_env

carica_env()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PERCORSO = os.path.join(DATA_DIR, "impostazioni.json")

_lock = threading.Lock()

# chiave interna -> variabile d'ambiente equivalente
DA_AMBIENTE = {
    "metodo_invio":   "METODO_INVIO",      # "smtp" oppure "blat"
    "smtp_host":      "SMTP_HOST",
    "smtp_port":      "SMTP_PORT",
    "smtp_ssl":       "SMTP_SSL",
    "smtp_user":      "SMTP_USER",
    "smtp_password":  "SMTP_PASSWORD",
    "smtp_from":      "SMTP_FROM",
    "blat_path":      "BLAT_PATH",         # percorso di blat.exe (solo Windows)
    "notify_email":   "NOTIFY_EMAIL",
    "app_base_url":   "APP_BASE_URL",
}

# Valori di partenza, gia' compilati nella pagina.
# Devono essere valori VERI e non semplici suggerimenti grigi: un campo che
# sembra pieno ma e' vuoto fa credere di aver configurato tutto, e l'invio
# fallisce senza che si capisca il perche'.
PREDEFINITI = {
    "metodo_invio":  "smtp",
    "blat_path":     "blat.exe",
    "smtp_host":     "mail.mclink.it",
    "smtp_port":     "465",
    "smtp_ssl":      "1",
    "smtp_user":     "assistenza@sigrafilm.it",
    "notify_email":  "assistenza@sigrafilm.it",
    "app_base_url":  "http://188.8.192.138:5000",
}


def _leggi_file() -> dict:
    if not os.path.isfile(PERCORSO):
        return {}
    try:
        with open(PERCORSO, encoding="utf-8") as f:
            dati = json.load(f)
        return dati if isinstance(dati, dict) else {}
    except Exception as e:
        print(f"[impostazioni] File illeggibile, uso i valori d'ambiente: {e}")
        return {}


def tutte() -> dict:
    """
    Impostazioni correnti: file salvato, poi ambiente, poi predefiniti.
    Rilette a ogni chiamata, così le modifiche dalla pagina hanno effetto subito.
    """
    salvate = _leggi_file()
    risultato = {}
    for chiave, var_ambiente in DA_AMBIENTE.items():
        valore = salvate.get(chiave)
        if valore in (None, ""):
            valore = os.environ.get(var_ambiente, "").strip()
        if valore in (None, ""):
            valore = PREDEFINITI.get(chiave, "")
        risultato[chiave] = valore
    return risultato


def leggi(chiave: str, predefinito: str = "") -> str:
    return tutte().get(chiave) or predefinito


def salva(nuove: dict) -> None:
    """
    Aggiorna le impostazioni sul disco.

    Scrittura atomica come per i file Excel: si scrive su un temporaneo e si
    rinomina, così un'interruzione non lascia un file mezzo scritto.
    Un valore vuoto per la password significa "lascia quella di prima",
    perché la pagina non la rimanda mai indietro in chiaro.
    """
    with _lock:
        correnti = _leggi_file()
        for chiave, valore in nuove.items():
            if chiave not in DA_AMBIENTE:
                continue
            if chiave == "smtp_password" and not str(valore).strip():
                continue          # non sovrascrivere con vuoto
            correnti[chiave] = str(valore).strip()

        os.makedirs(DATA_DIR, exist_ok=True)
        fd, temporaneo = tempfile.mkstemp(dir=DATA_DIR, prefix=".impostazioni.",
                                          suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(correnti, f, indent=2, ensure_ascii=False)
            os.replace(temporaneo, PERCORSO)
            try:
                os.chmod(PERCORSO, 0o600)   # su Windows viene ignorato
            except OSError:
                pass
        except Exception:
            try:
                os.remove(temporaneo)
            except OSError:
                pass
            raise


def campi_mancanti() -> list:
    """
    Nomi dei campi obbligatori ancora vuoti, come si chiamano nella pagina.

    Restituisce la lista invece di un semplice sì/no perché dire soltanto
    "compila i campi obbligatori" non aiuta: bisogna dire quali.
    """
    imp = tutte()
    mancanti = []

    if not imp.get("notify_email"):
        mancanti.append("Manda le notifiche a")

    metodo = imp.get("metodo_invio")

    # smtp e blat usano gli stessi dati del server di posta
    if not imp.get("smtp_host"):
        mancanti.append("Server")
    if not imp.get("smtp_user"):
        mancanti.append("Casella")
    if metodo == "blat" and not imp.get("blat_path"):
        mancanti.append("Percorso di blat.exe")
    return mancanti


def configurato() -> bool:
    """True se c'è abbastanza per provare a inviare."""
    return not campi_mancanti()
