"""
main.py
-------
Utilisation :

  # 1. Indexer ta bibliothèque
  python cli/main.py index songs/

  # 2. Identifier un extrait
  python cli/main.py identify queries/extrait.mp3

  # 2bis. Identifier ET confirmer/corriger le résultat (recommandé)
  python cli/main.py identify queries/extrait.mp3 --confirm

  # 3. Calibrer : vérifier que l'algo retrouve bien des morceaux DÉJÀ connus
  python cli/main.py selftest

  # 4. Voir les stats de précision accumulées via --confirm
  python cli/main.py stats
"""

import argparse
import getpass
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import FingerprintDB, load_audio
from fingerprint import SAMPLE_RATE
import feedback
import backup

CLI_USERNAME = f"cli:{getpass.getuser()}"

DB_PATH = Path("db/fingerprints.pkl")


def cmd_index(args):
    if args.rebuild:
        saved = backup.create_backup("before_rebuild")
        if saved:
            print(f"Sauvegarde de sécurité créée avant rebuild : {saved}")
        print("Réindexation complète demandée : la base existante est ignorée/reconstruite.")
        db = FingerprintDB()
    elif DB_PATH.exists():
        print("Base existante trouvée, on continue à l'enrichir (les morceaux déjà indexés sont ignorés).")
        db = FingerprintDB.load(DB_PATH)
    else:
        db = FingerprintDB()

    db.index_folder(args.folder)
    db.save(DB_PATH)


def _prompt_correction(db, query_file, results):
    """
    Affiche les résultats, demande à l'utilisateur de confirmer le bon,
    ou de chercher/indiquer le bon morceau si ce n'est pas dans la liste.
    Enregistre le résultat dans corrections.json.
    """
    print("\nCe résultat est-il correct ?")
    if results:
        for i, (song_id, title, count, offset_sec) in enumerate(results, 1):
            print(f"  {i}. {title}  (confiance={count}, début={offset_sec:.1f}s)")
    else:
        print("  (aucun résultat proposé)")
    print("  n. Aucun de ceux-ci / le morceau n'est pas dans la liste")
    print("  s. Passer (ne pas enregistrer de correction)")

    choice = input("Ton choix : ").strip().lower()

    if choice == "s":
        return

    if choice.isdigit() and results and 1 <= int(choice) <= len(results):
        idx = int(choice) - 1
        song_id, title, count, _ = results[idx]
        predicted = results[0]
        feedback.record_correction(
            query_file, predicted[0], predicted[1], predicted[2],
            correct_song_id=song_id, correct_title=title,
            was_correct=(idx == 0),
            username=CLI_USERNAME,
        )
        print(f"Confirmé : '{title}'. Enregistré.")
        return

    # choix == "n" ou entrée invalide -> recherche manuelle
    search = input("Nom (ou partie du nom) du bon morceau (laisser vide si absent de ta base) : ").strip()
    predicted = results[0] if results else (None, None, 0, None)

    if not search:
        feedback.record_correction(
            query_file, predicted[0], predicted[1], predicted[2],
            correct_song_id=None, correct_title="(absent de la base)",
            was_correct=False,
            username=CLI_USERNAME,
        )
        print("Enregistré : morceau absent de la base.")
        return

    matches = db.search_by_title(search)
    if not matches:
        print(f"Aucun morceau trouvé contenant '{search}' dans la base.")
        feedback.record_correction(
            query_file, predicted[0], predicted[1], predicted[2],
            correct_song_id=None, correct_title=f"(non trouvé: '{search}')",
            was_correct=False,
            username=CLI_USERNAME,
        )
        return

    print("Morceaux trouvés :")
    for i, (song_id, title) in enumerate(matches, 1):
        print(f"  {i}. {title}")
    pick = input("Lequel est le bon ? (numéro, ou vide pour annuler) : ").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(matches):
        song_id, title = matches[int(pick) - 1]
        feedback.record_correction(
            query_file, predicted[0], predicted[1], predicted[2],
            correct_song_id=song_id, correct_title=title,
            was_correct=False,
            username=CLI_USERNAME,
        )
        print(f"Correction enregistrée : '{title}'.")
    else:
        print("Annulé, rien d'enregistré.")


def cmd_identify(args):
    if not DB_PATH.exists():
        print("Aucune base trouvée. Lance d'abord : python cli/main.py index songs/")
        return

    db = FingerprintDB.load(DB_PATH)
    print(f"Base chargée : {len(db.songs)} morceaux, {len(db.hash_index)} hash")
    print(f"\nAnalyse de {args.file} ...")

    results = db.identify(args.file, top_n=args.top, min_confidence=args.min_confidence)

    if not results:
        print("\nAucun match trouvé (le morceau n'est probablement pas dans la base).")
    else:
        print("\nRésultats :")
        for i, (song_id, title, count, offset_sec) in enumerate(results, 1):
            print(f"  {i}. {title:40s}  confiance={count:4d}  début_estimé={offset_sec:.1f}s")

    if args.confirm:
        _prompt_correction(db, args.file, results)


def cmd_selftest(args):
    """
    Calibration : prend N morceaux déjà indexés au hasard, en extrait un
    passage de quelques secondes, et vérifie que identify() les retrouve.
    Donne une vraie valeur de référence pour la confiance attendue.
    """
    if not DB_PATH.exists():
        print("Aucune base trouvée. Lance d'abord : python cli/main.py index songs/")
        return

    db = FingerprintDB.load(DB_PATH)
    if not db.songs:
        print("Base vide.")
        return

    n = min(args.n, len(db.songs))
    sample = random.sample(list(db.songs.items()), n)

    print(f"Selftest sur {n} morceau(x) déjà indexés (extrait de {args.clip_seconds}s, sans bruit) :\n")
    n_ok = 0
    for song_id, info in sample:
        path = info["path"]
        title = info["title"]
        try:
            audio = load_audio(path)
        except Exception as e:
            print(f"  [ERREUR chargement] {title}: {e}")
            continue

        duration = len(audio) / SAMPLE_RATE
        if duration <= args.clip_seconds + 2:
            start = 0
        else:
            start = random.uniform(2, duration - args.clip_seconds - 2)
        start_sample = int(start * SAMPLE_RATE)
        end_sample = start_sample + int(args.clip_seconds * SAMPLE_RATE)
        clip = audio[start_sample:end_sample]

        results = db.identify(clip, top_n=1, min_confidence=1)
        if results and results[0][0] == song_id:
            n_ok += 1
            print(f"  [OK]   {title:40s}  confiance={results[0][2]:4d}  (extrait pris à {start:.1f}s)")
        elif results:
            print(f"  [FAUX] {title:40s}  -> a trouvé '{results[0][1]}' (confiance={results[0][2]}) au lieu du bon")
        else:
            print(f"  [RATÉ] {title:40s}  -> aucun match du tout (extrait pris à {start:.1f}s)")

    print(f"\nScore : {n_ok}/{n} correctement retrouvés.")
    print("Si ce score est mauvais sur des morceaux DÉJÀ dans la base et SANS bruit,")
    print("le problème vient des paramètres de fingerprint.py, pas du bruit ambiant.")


def cmd_stats(args):
    feedback.print_stats()


def main():
    parser = argparse.ArgumentParser(description="Prototype Shazam-like")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Indexer un dossier de musique")
    p_index.add_argument("folder", help="Chemin du dossier contenant tes fichiers audio")
    p_index.add_argument("--rebuild", action="store_true", help="Réindexer tout depuis zéro (nécessaire après un changement de config.json)")
    p_index.set_defaults(func=cmd_index)

    p_identify = sub.add_parser("identify", help="Identifier un extrait audio")
    p_identify.add_argument("file", help="Chemin du fichier à identifier")
    p_identify.add_argument("--top", type=int, default=3, help="Nombre de résultats à afficher")
    p_identify.add_argument("--min-confidence", type=int, default=3, help="Nombre minimum de hash alignés pour valider un match")
    p_identify.add_argument("--confirm", action="store_true", help="Demander confirmation/correction après le résultat")
    p_identify.set_defaults(func=cmd_identify)

    p_selftest = sub.add_parser("selftest", help="Calibration : teste l'algo sur des morceaux déjà indexés")
    p_selftest.add_argument("--n", type=int, default=8, help="Nombre de morceaux à tester")
    p_selftest.add_argument("--clip-seconds", type=float, default=10.0, help="Durée de l'extrait testé")
    p_selftest.set_defaults(func=cmd_selftest)

    p_stats = sub.add_parser("stats", help="Afficher les statistiques de précision (corrections enregistrées)")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
