"""
Caricamento delle impostazioni dal file .env.

Sta in un modulo a parte perché lo usano sia app.py sia mailer.py: se il
caricamento vivesse solo dentro app.py, importare mailer per conto suo
(da uno script, da un test) lascerebbe le notifiche spente senza dirlo.

La funzione è idempotente: chiamarla più volte non fa danni e le variabili
d'ambiente di sistema hanno sempre la precedenza sul file.
"""
import os

PERCORSO_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

_gia_caricato = False


def carica_env(percorso: str = PERCORSO_ENV) -> None:
    """Legge il file .env e popola os.environ con le chiavi mancanti."""
    global _gia_caricato
    if _gia_caricato:
        return
    _gia_caricato = True

    if not os.path.isfile(percorso):
        return
    try:
        with open(percorso, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if not riga or riga.startswith("#") or "=" not in riga:
                    continue
                chiave, _, valore = riga.partition("=")
                chiave = chiave.strip()
                valore = valore.strip().strip('"').strip("'")
                # Le variabili di sistema hanno la precedenza sul file
                if chiave and chiave not in os.environ:
                    os.environ[chiave] = valore
    except Exception as e:
        print(f"[env] Impossibile leggere .env: {e}")
