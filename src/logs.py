"""
logs.py
-------
Journal centralisé : tout passe par ici (recherches, erreurs, calibration...)
pour pouvoir être affiché en temps réel dans l'interface web (onglet Logs)
via Server-Sent Events, en plus d'être écrit dans db/app.log.
"""

import threading
from collections import deque
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("db/app.log")
_lock = threading.Lock()
_buffer = deque(maxlen=500)
_next_id = 1


def log(message, level="INFO"):
    global _next_id
    with _lock:
        entry = {
            "id": _next_id,
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        _buffer.append(entry)
        _next_id += 1

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{entry['time']}] {level}: {message}\n")
    except OSError:
        pass

    return entry


def get_since(last_id):
    with _lock:
        return [e for e in _buffer if e["id"] > last_id]


def get_all():
    with _lock:
        return list(_buffer)
