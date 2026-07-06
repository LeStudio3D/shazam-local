"""
dedup.py
--------
Détecte les morceaux en double dans ta base (même chanson indexée depuis
plusieurs playlists) en comparant les empreintes ENTRE ELLES, PAR PAIRE
(pas de regroupement en chaîne : deux morceaux ne sont proposés comme
doublons que si LEUR chevauchement mutuel est fort, dans les DEUX sens).
Ne touche jamais aux fichiers MP3 sur le disque — seulement à l'index.

Usage :
    python cli/dedup.py                  # détecte + résolution interactive
    python cli/dedup.py --threshold 0.6  # encore plus strict
"""

import argparse
import sys
from collections import defaultdict, Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database import FingerprintDB, load_audio
from fingerprint import fingerprint_audio
import backup

DB_PATH = Path("db/fingerprints.pkl")


def find_duplicate_pairs(db, threshold_ratio=0.5):
    """
    Pour chaque morceau, on refingerprinte son audio et on compte combien
    de ses hash apparaissent aussi sous chaque AUTRE song_id dans la base.
    On ne retient une paire comme doublon que si le ratio de recouvrement
    est fort DANS LES DEUX SENS (min(ratio_A->B, ratio_B->A) >= seuil).
    Ça évite les faux positifs en chaîne : A et C ne sont jamais comparés
    l'un à l'autre juste parce qu'ils ressemblent tous les deux un peu à B.
    """
    song_ids = list(db.songs.keys())
    total_hashes = {}
    match_counts = {}

    print(f"Analyse de {len(song_ids)} morceau(x) pour détecter les doublons...")
    for idx, sid in enumerate(song_ids, 1):
        info = db.songs[sid]
        path = info["path"]
        if not Path(path).exists():
            print(f"  [{idx}/{len(song_ids)}] fichier introuvable, ignoré : {path}")
            total_hashes[sid] = 0
            match_counts[sid] = {}
            continue
        try:
            audio = load_audio(path)
        except Exception as e:
            print(f"  [{idx}/{len(song_ids)}] erreur de lecture, ignoré : {info['title']} ({e})")
            total_hashes[sid] = 0
            match_counts[sid] = {}
            continue

        hashes = fingerprint_audio(audio)
        total_hashes[sid] = len(hashes) or 1

        counts = Counter()
        for h, _ in hashes:
            if h in db.hash_index:
                for other_sid, _ in db.hash_index[h]:
                    if other_sid != sid:
                        counts[other_sid] += 1
        match_counts[sid] = counts

        if idx % 20 == 0:
            print(f"  ... {idx}/{len(song_ids)} analysés")

    # Comparaison par paire, avec critère symétrique
    pairs = []
    seen = set()
    for sid in song_ids:
        for other_sid, cnt_sid_to_other in match_counts[sid].items():
            key = tuple(sorted((sid, other_sid)))
            if key in seen:
                continue
            seen.add(key)

            cnt_other_to_sid = match_counts.get(other_sid, {}).get(sid, 0)
            ratio_sid = cnt_sid_to_other / total_hashes.get(sid, 1)
            ratio_other = cnt_other_to_sid / total_hashes.get(other_sid, 1)
            min_ratio = min(ratio_sid, ratio_other)

            if min_ratio >= threshold_ratio:
                pairs.append((sid, other_sid, min_ratio))

    pairs.sort(key=lambda p: -p[2])
    return pairs


def resolve_interactive(db, pairs):
    total_removed = 0
    already_removed = set()

    for sid_a, sid_b, ratio in pairs:
        if sid_a in already_removed or sid_b in already_removed:
            continue  # déjà traité via une autre paire
        if sid_a not in db.songs or sid_b not in db.songs:
            continue

        info_a = db.songs[sid_a]
        info_b = db.songs[sid_b]
        print(f"\nDoublon probable (recouvrement mutuel : {100*min(ratio, 1.0):.0f}%) :")
        print(f"  1. {info_a['title']}")
        print(f"     {info_a['path']}")
        print(f"  2. {info_b['title']}")
        print(f"     {info_b['path']}")

        choice = input("Lequel garder ? (1, 2, 'a' = garder les deux, 's' = passer) : ").strip().lower()
        if choice in ("a", "s", ""):
            continue
        if choice not in ("1", "2"):
            print("Choix invalide, paire ignorée.")
            continue

        keep_sid = sid_a if choice == "1" else sid_b
        remove_sid = sid_b if choice == "1" else sid_a
        removed_title = db.songs[remove_sid]["title"]

        del db.songs[remove_sid]
        for h in list(db.hash_index.keys()):
            filtered = [(s, t) for s, t in db.hash_index[h] if s != remove_sid]
            if filtered:
                db.hash_index[h] = filtered
            else:
                del db.hash_index[h]

        already_removed.add(remove_sid)
        total_removed += 1
        print(f"Gardé : '{db.songs[keep_sid]['title']}'. Supprimé de l'index : '{removed_title}'")

    return total_removed


def main():
    parser = argparse.ArgumentParser(description="Détection et résolution des doublons")
    parser.add_argument("--threshold", type=float, default=0.5,
                         help="Ratio minimal de recouvrement mutuel pour proposer un doublon (défaut: 0.5)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("Aucune base trouvée. Lance d'abord : python cli/main.py index songs/")
        return

    db = FingerprintDB.load(DB_PATH)
    pairs = find_duplicate_pairs(db, threshold_ratio=args.threshold)

    if not pairs:
        print("\nAucun doublon détecté.")
        return

    print(f"\n{len(pairs)} paire(s) de doublons potentiels trouvée(s) (triées par similarité décroissante).")
    removed = resolve_interactive(db, pairs)

    if removed:
        saved = backup.create_backup("before_dedup")
        if saved:
            print(f"Sauvegarde de sécurité créée : {saved}")
        db.save(DB_PATH)
        print(f"\n{removed} morceau(x) retiré(s) de l'index. Base sauvegardée.")
        print("(les fichiers MP3 originaux n'ont pas été touchés sur le disque)")
    else:
        print("\nAucune modification enregistrée.")


if __name__ == "__main__":
    main()
