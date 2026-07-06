"""
user_calibration.py
--------------------
Contrairement à calibrate.py (réservé aux admins, qui teste des paramètres
d'INDEXATION et doit ré-analyser l'audio), ceci ne touche qu'au SEUIL DE
CONFIANCE de recherche (min_confidence) — un réglage propre à chaque
utilisateur qui ne nécessite pas de réindexer quoi que ce soit.

On se base uniquement sur l'historique de corrections déjà confirmées par
cet utilisateur (confidence obtenue + était-ce correct ou non), et on teste
une série de seuils candidats pour trouver celui qui aurait donné le plus
de bonnes décisions (accepter un vrai match, rejeter un faux).
"""

import feedback


def compute_best_threshold(username, default=3, min_examples=3):
    """
    Renvoie (best_threshold, nb_exemples_utilisés, score_pourcentage) ou
    (default, 0, None) si pas assez de données pour cet utilisateur.
    """
    all_corrections = feedback.load_corrections()
    user_corrections = [
        c for c in all_corrections
        if c.get("username") == username and c.get("confidence") is not None
    ]

    if len(user_corrections) < min_examples:
        return default, len(user_corrections), None

    confidences = sorted(set(c["confidence"] for c in user_corrections))
    candidates = range(1, max(confidences, default=default) + 2)

    best_t, best_score = default, None
    for t in candidates:
        score = 0
        for c in user_corrections:
            accepted = c["confidence"] >= t
            if c["was_correct"] and accepted:
                score += 1        # bon match accepté : bien
            elif (not c["was_correct"]) and not accepted:
                score += 1        # mauvais match rejeté : bien
            elif c["was_correct"] and not accepted:
                score -= 1        # bon match raté (seuil trop strict) : mauvais
            else:
                score -= 1        # mauvais match accepté (seuil trop permissif) : mauvais

        if best_score is None or score > best_score:
            best_score, best_t = score, t

    accuracy_pct = round(100 * (best_score + len(user_corrections)) / (2 * len(user_corrections)))
    return best_t, len(user_corrections), accuracy_pct
