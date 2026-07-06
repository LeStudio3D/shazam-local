"""
fingerprint.py
--------------
Coeur de l'algo (façon Shazam / Avery Wang 2003) :
1. spectrogramme (FFT glissante)
2. extraction des pics locaux (constellation map)
3. hash combinatoire de paires de pics (anchor -> target)

Ce module ne dépend d'aucun format de fichier particulier : on lui donne
un signal audio (numpy array, mono, float) + son sample rate, il renvoie
des hash. Le chargement du fichier (mp3/wav/...) se fait dans database.py.
"""

import hashlib
import json
import struct
from pathlib import Path
import numpy as np
from scipy import signal as sig
from scipy.ndimage import maximum_filter

# ---- Paramètres de l'algo (à garder identiques entre indexation et recherche !) ----
# Valeurs par défaut. Si config.json existe (créé par calibrate.py ou la future
# page de réglages), ses valeurs les écrasent au chargement du module.
SAMPLE_RATE = 22050      # on downsample tout à 22.05kHz : suffisant pour l'identification, plus rapide
WINDOW_SIZE = 4096       # taille de la fenêtre FFT
HOP_SIZE = 2048          # chevauchement (50%)
AMP_MIN_DB = -40         # seuil minimal d'amplitude pour qu'un point soit considéré comme un "pic"
NEIGHBORHOOD = (20, 20)  # taille du voisinage (freq_bins, time_bins) pour chercher les maxima locaux
FAN_OUT = 5              # nb de pics "cible" associés à chaque pic "ancre"
TIME_WINDOW = 100        # fenêtre temporelle max (en bins) pour chercher des cibles
MIN_TIME_DELTA = 1
MIN_CONFIDENCE = 3       # nombre minimum de hash alignés pour valider un match

CONFIG_PATH = Path("config.json")


def _load_config():
    global AMP_MIN_DB, NEIGHBORHOOD, FAN_OUT, TIME_WINDOW, MIN_CONFIDENCE
    if not CONFIG_PATH.exists():
        return
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        AMP_MIN_DB = cfg.get("amp_min_db", AMP_MIN_DB)
        nb = cfg.get("neighborhood", list(NEIGHBORHOOD))
        NEIGHBORHOOD = tuple(nb)
        FAN_OUT = cfg.get("fan_out", FAN_OUT)
        TIME_WINDOW = cfg.get("time_window", TIME_WINDOW)
        MIN_CONFIDENCE = cfg.get("min_confidence", MIN_CONFIDENCE)
    except Exception as e:
        print(f"[fingerprint] config.json invalide, valeurs par défaut utilisées ({e})")


_load_config()


def compute_spectrogram(audio, sr=SAMPLE_RATE):
    f, t, Sxx = sig.spectrogram(
        audio, fs=sr, window="hann",
        nperseg=WINDOW_SIZE, noverlap=WINDOW_SIZE - HOP_SIZE,
        mode="magnitude"
    )
    Sxx_db = 20 * np.log10(Sxx + 1e-10)
    return f, t, Sxx_db


def find_peaks_2d(Sxx_db):
    local_max = maximum_filter(Sxx_db, size=NEIGHBORHOOD) == Sxx_db
    above_thresh = Sxx_db > AMP_MIN_DB
    peaks_mask = local_max & above_thresh
    freq_idx, time_idx = np.where(peaks_mask)
    return list(zip(time_idx, freq_idx))  # (t_bin, f_bin)


def _hash_to_int64(raw: str) -> int:
    """
    Convertit une chaîne (f1|f2|delta_t) en entier signé 64-bit.
    On utilise les 8 premiers octets du SHA1 interprétés comme un int64 signé,
    ce qui correspond exactement au type BIGINT de PostgreSQL : compact,
    indexable très rapidement, pas de conversion nécessaire.
    """
    digest = hashlib.sha1(raw.encode()).digest()
    return struct.unpack(">q", digest[:8])[0]


def generate_hashes(peaks):
    """Renvoie une liste de (hash_int64, t_bin_ancre)."""
    peaks_sorted = sorted(peaks, key=lambda p: p[0])
    hashes = []

    for i, (t1, f1) in enumerate(peaks_sorted):
        targets_found = 0
        for j in range(i + 1, len(peaks_sorted)):
            t2, f2 = peaks_sorted[j]
            delta_t = t2 - t1
            if delta_t < MIN_TIME_DELTA:
                continue
            if delta_t > TIME_WINDOW:
                break
            raw = f"{f1}|{f2}|{delta_t}"
            h = _hash_to_int64(raw)
            hashes.append((h, t1))
            targets_found += 1
            if targets_found >= FAN_OUT:
                break

    return hashes


def fingerprint_audio(audio, sr=SAMPLE_RATE):
    """Pipeline complet : audio (numpy array) -> liste de (hash, t_bin)."""
    _, _, Sxx_db = compute_spectrogram(audio, sr)
    peaks = find_peaks_2d(Sxx_db)
    return generate_hashes(peaks)


def time_bin_to_seconds(t_bin, sr=SAMPLE_RATE):
    """Convertit un index de bin temporel en secondes réelles (utile pour l'affichage)."""
    hop_seconds = HOP_SIZE / sr
    return t_bin * hop_seconds
