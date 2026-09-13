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
    "metodo_invio":   "METODO_INVIO",      # "smtp", "blat" oppure "web"
    "smtp_host":      "SMTP_HOST",
    "smtp_port":      "SMTP_PORT",
    "smtp_ssl":       "SMTP_SSL",
    "smtp_user":      "SMTP_USER",
    "smtp_password":  "SMTP_PASSWORD",
    "smtp_from":      "SMTP_FROM",
    "blat_path":      "BLAT_PATH",         # percorso di blat.exe (solo Windows)
    "api_key":        "EMAIL_API_KEY",     # chiave del servizio web (Brevo)
    "notify_email":   "NOTIFY_EMAIL",
    "app_base_url":   "APP_BASE_URL",
}

PREDEFINITI = {
    "metodo_invio":  "smtp",
    "blat_path":     "blat.exe",
    "smtp_port":     "465",
    "smtp_ssl":      "1",
    "notify_email":  "assistenza@sigrafilm.it",
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
            if chiave in ("smtp_password", "api_key") and not str(valore).strip():
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


def configurato() -> bool:
    """True se c'è abbastanza per provare a inviare."""
    imp = tutte()
    if not imp.get("notify_email"):
        return False
    metodo = imp.get("metodo_invio")
    if metodo == "web":
        return bool(imp.get("api_key") and (imp.get("smtp_from") or imp.get("smtp_user")))
    if metodo == "blat":
        return bool(imp.get("blat_path") and imp.get("smtp_host") and imp.get("smtp_user"))
    return bool(imp.get("smtp_host") and imp.get("smtp_user"))
