"""
Reset d'emergenza della password admin.

Sostituisce la vecchia route web "/reset-admin-password-7x9k", che era
raggiungibile da chiunque su internet senza autenticazione.

Funziona solo da riga di comando sul PC dove gira il sito:

    python reset_admin.py

Chiede la nuova password a schermo (non resta nella cronologia dei comandi)
e non stampa mai la password digitata.
"""
import sys
import getpass

from werkzeug.security import generate_password_hash

from storage import store


def main() -> int:
    print("=== Reset password amministratore — SigraFilm NOC ===\n")

    utenti_admin = [u for u in store.get_all_users() if u.role == "admin"]
    if utenti_admin:
        print("Amministratori presenti:")
        for u in utenti_admin:
            print(f"   - {u.username}")
        print()
        nome = input("Quale username vuoi reimpostare? [admin] ").strip() or "admin"
    else:
        print("Nessun amministratore trovato: ne verrà creato uno nuovo.\n")
        nome = input("Username del nuovo amministratore: [admin] ").strip() or "admin"

    pwd1 = getpass.getpass("Nuova password (minimo 8 caratteri): ")
    if len(pwd1) < 8:
        print("\nERRORE: la password deve avere almeno 8 caratteri.")
        return 1
    pwd2 = getpass.getpass("Ripeti la password: ")
    if pwd1 != pwd2:
        print("\nERRORE: le due password non coincidono.")
        return 1

    u = store.get_user_by_username(nome)
    if u:
        u.password_hash = generate_password_hash(pwd1)
        u.role = "admin"
        store.update_user(u)
        print(f"\nFatto: password di '{nome}' aggiornata.")
    else:
        store.create_user(username=nome,
                          password_hash=generate_password_hash(pwd1),
                          role="admin")
        print(f"\nFatto: amministratore '{nome}' creato.")

    print("Ora puoi accedere al sito con le nuove credenziali.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAnnullato.")
        sys.exit(1)
