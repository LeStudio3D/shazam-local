"""
calibrate.py
------------
C'est ici que tes corrections (db/corrections.json, remplies via
`identify --confirm`) servent enfin à quelque chose : on teste plusieurs
combinaisons de paramètres de fingerprint.py sur un échantillon de ta
bibliothèque, contre tes exemples confirmés, et on garde la config qui
identifie le mieux.

Ce n'est pas un réseau de neurones qui "apprend" — c'est une recherche
systématique (grid search) du meilleur réglage, comme un technicien qui
essaierait plusieurs réglages d'antenne et garderait le meilleur. Mais
concrètement, plus tu utilises --confirm, plus cette calibration devient fiable.

Usage :
    python cli/calibrate.py

Nécessite au moins 3 corrections enregistrées avec un morceau correct connu
(via `identify --confirm`, en indiquant le bon morceau quand il est dans ta base).
"""

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fingerprint
from database import FingerprintDB, load_audio
import feedback
import backup

DB_PATH = Path("db/fingerprints.pkl")
CONFIG_PATH = Path("config.json")

# Grille de paramètres à tester. On reste volontairement petit (5 combos)
# car chaque combo nécessite de refingerprinter l'échantillon de morceaux.
PARAM_GRID = [
    {"amp_min_db": -40, "neighborhood": [20, 20], "fan_out": 5, "time_window": 100},   # défaut actuel
    {"amp_min_db": -35, "neighborhood": [20, 20], "fan_out": 5, "time_window": 100},   # pics plus stricts (moins de bruit)
    {"amp_min_db": -45, "neighborhood": [20, 20], "fan_out": 8, "time_window": 150},   # plus permissif, plus de hash
    {"amp_min_db": -40, "neighborhood": [15, 15], "fan_out": 8, "time_window": 100},   # voisinage plus fin
    {"amp_min_db": -40, "neighborhood": [25, 25], "fan_out": 5, "time_window": 200},   # voisinage plus large
]

MAX_LIBRARY_SAMPLE = 40  # pour garder le calibrage rapide sur une grosse bibliothèque


def _apply_config(cfg):
    """Applique une config directement sur le module fingerprint (sans passer par le fichier, pour aller vite)."""
    fingerprint.AMP_MIN_DB = cfg["amp_min_db"]
    fingerprint.NEIGHBORHOOD = tuple(cfg["neighborhood"])
    fingerprint.FAN_OUT = cfg["fan_out"]
    fingerprint.TIME_WINDOW = cfg["time_window"]


def _build_sample_db(song_paths_ids):
    """Reconstruit une mini-base (juste pour l'échantillon) avec la config actuellement appliquée."""
    db = FingerprintDB()
    for song_id, path in song_paths_ids:
        db.add_song(Path(path), verbose=False)
    return db


def main():
    if not DB_PATH.exists():
        print("Aucune base trouvée. Lance d'abord : python cli/main.py index songs/")
        return

    full_db = FingerprintDB.load(DB_PATH)
    corrections = feedback.load_corrections()

    # On ne garde que les corrections exploitables : morceau correct connu et fichier toujours présent
    usable = []
    for c in corrections:
        if not c.get("correct_song_id"):
            continue
        if not Path(c["query_file"]).exists():
            continue
        usable.append((c["query_file"], c["correct_song_id"]))

    if len(usable) < 3:
        print(f"Seulement {len(usable)} correction(s) exploitable(s) trouvée(s) dans db/corrections.json.")
        print("Il en faut au moins 3 (avec morceau correct identifié et fichier toujours présent).")
        print("Utilise : python cli/main.py identify <fichier> --confirm   pour en ajouter.")
        return

    print(f"{len(usable)} correction(s) exploitable(s) trouvée(s).")

    # Échantillon de la bibliothèque pour garder le calibrage rapide
    all_songs = list(full_db.songs.items())
    if len(all_songs) > MAX_LIBRARY_SAMPLE:
        # on force à inclure les morceaux concernés par les corrections + un échantillon aléatoire
        needed_ids = {sid for _, sid in usable}
        forced = [(sid, info) for sid, info in all_songs if sid in needed_ids]
        rest = [(sid, info) for sid, info in all_songs if sid not in needed_ids]
        random.shuffle(rest)
        sample = forced + rest[: max(0, MAX_LIBRARY_SAMPLE - len(forced))]
    else:
        sample = all_songs

    sample_ids = {sid for sid, _ in sample}
    # si un morceau correct référencé dans les corrections n'est pas dans l'échantillon, on l'ajoute
    missing = {sid for _, sid in usable} - sample_ids
    for sid in missing:
        if sid in full_db.songs:
            sample.append((sid, full_db.songs[sid]))

    sample_paths = [(sid, info["path"]) for sid, info in sample]
    print(f"Calibrage sur un échantillon de {len(sample_paths)} morceau(x) de ta bibliothèque.\n")

    results_per_config = []

    for cfg in PARAM_GRID:
        _apply_config(cfg)
        t0 = time.time()
        mini_db = _build_sample_db(sample_paths)

        correct = 0
        total_confidence = 0
        for query_file, correct_song_id in usable:
            audio = load_audio(query_file)
            res = mini_db.identify(audio, top_n=1, min_confidence=1)
            if res and res[0][0] == correct_song_id:
                correct += 1
                total_confidence += res[0][2]

        accuracy = correct / len(usable)
        avg_conf = total_confidence / correct if correct else 0
        elapsed = time.time() - t0

        print(f"Config {cfg}")
        print(f"  -> précision: {correct}/{len(usable)} ({100*accuracy:.0f}%)   confiance moyenne sur les bons matchs: {avg_conf:.0f}   ({elapsed:.1f}s)")

        results_per_config.append((cfg, accuracy, avg_conf))

    # meilleur = plus haute précision, puis plus haute confiance moyenne en cas d'égalité
    best_cfg, best_acc, best_conf = max(results_per_config, key=lambda r: (r[1], r[2]))

    print(f"\n>>> Meilleure config : {best_cfg}")
    print(f">>> Précision {100*best_acc:.0f}%, confiance moyenne {best_conf:.0f}")

    best_cfg_to_save = dict(best_cfg)
    best_cfg_to_save["min_confidence"] = 3
    saved = backup.create_backup("before_calibrate")
    if saved:
        print(f"Sauvegarde de sécurité créée : {saved}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(best_cfg_to_save, f, indent=2)
    print(f"\nSauvegardé dans {CONFIG_PATH}.")
    print("IMPORTANT : les hash ont changé, il faut réindexer toute la bibliothèque :")
    print("    python cli/main.py index songs --rebuild")


if __name__ == "__main__":
    main()
