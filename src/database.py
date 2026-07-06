"""
database.py
-----------
Gère :
- le chargement des fichiers audio (mp3, wav, flac, m4a...) via librosa
- l'indexation d'un dossier entier de musique
- la sauvegarde / le chargement de l'index sur disque (pickle)
- la recherche d'un extrait (query) contre l'index
"""

import pickle
import hashlib
from pathlib import Path
from collections import defaultdict, Counter

import numpy as np
import librosa

from fingerprint import fingerprint_audio, SAMPLE_RATE, time_bin_to_seconds

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}


def load_audio(path, sr=SAMPLE_RATE):
    """Charge un fichier audio et le convertit en mono, float, au sample rate voulu."""
    audio, _ = librosa.load(str(path), sr=sr, mono=True)
    return audio


def make_song_id(path: Path) -> str:
    """Id stable et court dérivé du chemin du fichier (pour éviter les collisions de noms)."""
    return hashlib.md5(str(path).encode()).hexdigest()[:12]


class FingerprintDB:
    def __init__(self):
        self.hash_index = defaultdict(list)   # hash -> [(song_id, t_bin), ...]
        self.songs = {}                       # song_id -> {"path": ..., "title": ...}

    def add_song(self, path: Path, verbose=True):
        path = Path(path)
        song_id = make_song_id(path)
        if song_id in self.songs:
            if verbose:
                print(f"  [déjà indexé] {path.name}")
            return

        audio = load_audio(path)
        hashes = fingerprint_audio(audio)
        for h, t_bin in hashes:
            self.hash_index[h].append((song_id, t_bin))

        self.songs[song_id] = {"path": str(path), "title": path.stem}
        if verbose:
            duration = len(audio) / SAMPLE_RATE
            print(f"  [OK] {path.name}  ({duration:.1f}s, {len(hashes)} hash)")

    def index_folder(self, folder):
        folder = Path(folder)
        files = [p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS]
        if not files:
            print(f"Aucun fichier audio trouvé dans {folder} (extensions supportées : {AUDIO_EXTENSIONS})")
            return
        print(f"Indexation de {len(files)} fichier(s) depuis {folder}...")
        for f in files:
            try:
                self.add_song(f)
            except Exception as e:
                print(f"  [ERREUR] {f.name}: {e}")
        print(f"Terminé. Base : {len(self.songs)} morceaux, {len(self.hash_index)} hash uniques.")

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"hash_index": dict(self.hash_index), "songs": self.songs}, f)
        print(f"Base sauvegardée : {path} ({len(self.songs)} morceaux, {len(self.hash_index)} hash)")

    @classmethod
    def load(cls, path):
        db = cls()
        with open(path, "rb") as f:
            data = pickle.load(f)
        db.hash_index = defaultdict(list, data["hash_index"])
        db.songs = data["songs"]
        return db

    def search_by_title(self, substring):
        """Recherche des morceaux indexés dont le titre contient `substring` (insensible à la casse)."""
        substring = substring.lower()
        return [
            (song_id, info["title"])
            for song_id, info in self.songs.items()
            if substring in info["title"].lower()
        ]

    def identify(self, query_path_or_audio, top_n=3, min_confidence=3):
        """
        Identifie un extrait audio. Accepte soit un chemin de fichier,
        soit un numpy array déjà chargé au bon sample rate.
        Renvoie une liste triée de (song_id, title, nb_hash_alignés, offset_sec).
        """
        if isinstance(query_path_or_audio, (str, Path)):
            audio = load_audio(query_path_or_audio)
        else:
            audio = query_path_or_audio

        query_hashes = fingerprint_audio(audio)

        offsets = defaultdict(Counter)
        for h, t_query in query_hashes:
            if h in self.hash_index:
                for song_id, t_db in self.hash_index[h]:
                    delta = t_db - t_query
                    offsets[song_id][delta] += 1

        results = []
        for song_id, counter in offsets.items():
            best_delta, best_count = counter.most_common(1)[0]
            if best_count >= min_confidence:
                title = self.songs[song_id]["title"]
                offset_sec = time_bin_to_seconds(best_delta)
                results.append((song_id, title, best_count, offset_sec))

        results.sort(key=lambda x: -x[2])
        return results[:top_n]
