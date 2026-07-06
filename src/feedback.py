"""
feedback.py
-----------
Journal de corrections : quand l'utilisateur confirme ou corrige un résultat
d'identification, on l'enregistre ici. Ce n'est PAS du machine learning
(l'algo ne "apprend" pas tout seul) : c'est un jeu de données de référence
(ground truth) qui nous permet ensuite de mesurer objectivement la précision
et d'ajuster les paramètres de fingerprint.py en connaissance de cause.
"""

import json
from pathlib import Path
from datetime import datetime

FEEDBACK_PATH = Path("db/corrections.json")


def load_corrections():
    if not FEEDBACK_PATH.exists():
        return []
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_corrections(corrections):
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(corrections, f, indent=2, ensure_ascii=False)


def record_correction(query_file, predicted_song_id, predicted_title, confidence,
                       correct_song_id, correct_title, was_correct, username="cli"):
    corrections = load_corrections()
    corrections.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "username": username,
        "query_file": str(query_file),
        "predicted_song_id": predicted_song_id,
        "predicted_title": predicted_title,
        "confidence": confidence,
        "correct_song_id": correct_song_id,
        "correct_title": correct_title,
        "was_correct": was_correct,
    })
    save_corrections(corrections)


def print_stats():
    corrections = load_corrections()
    if not corrections:
        print("Aucune correction enregistrée pour l'instant.")
        return
    total = len(corrections)
    correct = sum(1 for c in corrections if c["was_correct"])
    print(f"Corrections enregistrées : {total}")
    print(f"  - Prédictions correctes : {correct} ({100*correct/total:.0f}%)")
    print(f"  - Prédictions fausses/manquées : {total - correct} ({100*(total-correct)/total:.0f}%)")

    by_user = {}
    for c in corrections:
        u = c.get("username", "cli")
        by_user.setdefault(u, []).append(c)
    if len(by_user) > 1:
        print("\nPar utilisateur :")
        for u, items in by_user.items():
            ok = sum(1 for c in items if c["was_correct"])
            print(f"  - {u}: {ok}/{len(items)} ({100*ok/len(items):.0f}%)")

    wrong = [c for c in corrections if not c["was_correct"]]
    if wrong:
        print("\nCas ratés :")
        for c in wrong:
            pred = c["predicted_title"] or "(aucun match)"
            print(f"  - {Path(c['query_file']).name}: prédit='{pred}' (conf={c['confidence']}) -> correct='{c['correct_title']}'")
