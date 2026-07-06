"""
training.py
------------
Gère le dossier training/ : des échantillons de ~10s à déposer en vrac,
que l'admin revoit un par un dans l'interface web (identifier + confirmer),
sans jamais avoir à retaper une commande. On garde la trace des fichiers
déjà revus dans db/training_reviewed.json pour ne pas les repropser.
"""

import json
from pathlib import Path

TRAINING_DIR = Path("training")
REVIEWED_PATH = Path("db/training_reviewed.json")
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}


def load_reviewed():
    if not REVIEWED_PATH.exists():
        return set()
    with open(REVIEWED_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def mark_reviewed(relpath):
    reviewed = load_reviewed()
    reviewed.add(relpath)
    REVIEWED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEWED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(reviewed), f, indent=2, ensure_ascii=False)


def list_all_files():
    if not TRAINING_DIR.exists():
        return []
    return sorted(p for p in TRAINING_DIR.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS)


def next_unreviewed():
    """Renvoie (Path, relpath_str) du prochain fichier non revu, ou None si terminé."""
    reviewed = load_reviewed()
    for f in list_all_files():
        rel = str(f.relative_to(TRAINING_DIR))
        if rel not in reviewed:
            return f, rel
    return None


def queue_status():
    total = len(list_all_files())
    done = len(load_reviewed())
    return {"total": total, "reviewed": min(done, total), "remaining": max(0, total - done)}
