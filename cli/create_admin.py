"""
create_admin.py
---------------
Crée le premier compte administrateur (à lancer une seule fois avant
d'utiliser l'interface web).

Usage :
    python cli/create_admin.py
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import auth


def main():
    auth.init_db()
    print("Création d'un compte administrateur.\n")
    username = input("Nom d'utilisateur : ").strip()
    if not username:
        print("Nom d'utilisateur vide, abandon.")
        return

    password = getpass.getpass("Mot de passe : ")
    password2 = getpass.getpass("Confirme le mot de passe : ")
    if password != password2:
        print("Les mots de passe ne correspondent pas.")
        return
    if len(password) < 4:
        print("Mot de passe trop court (minimum 4 caractères).")
        return

    ok, err = auth.create_user(username, password, role="admin")
    if ok:
        print(f"\nCompte administrateur '{username}' créé avec succès.")
        print("Tu peux maintenant lancer : python web/webapp.py")
    else:
        print(f"\nErreur : {err}")


if __name__ == "__main__":
    main()
