"""
auth.py
-------
Gestion des utilisateurs : base SQLite (db/users.db), mots de passe hashés
(jamais stockés en clair, via werkzeug.security), rôles ('admin' / 'user'),
et décorateurs pour protéger les routes Flask.
"""

import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import session, redirect, url_for, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = Path("db/users.db")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            min_confidence INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        )
    """)
    # Migration douce si la base existait déjà sans ces colonnes (versions précédentes)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "failed_attempts" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
    if "locked_until" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    conn.commit()
    conn.close()


def create_user(username, password, role="user"):
    username = username.strip()
    if not username or not password:
        return False, "Nom d'utilisateur et mot de passe requis."
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, min_confidence, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, generate_password_hash(password), role, 3, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "Ce nom d'utilisateur existe déjà."
    finally:
        conn.close()


def check_lockout(username):
    """Renvoie (verrouillé: bool, minutes_restantes: int) pour ce nom d'utilisateur."""
    conn = get_conn()
    row = conn.execute("SELECT locked_until FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row or not row["locked_until"]:
        return False, 0
    locked_until = datetime.fromisoformat(row["locked_until"])
    if datetime.now() >= locked_until:
        return False, 0
    remaining = int((locked_until - datetime.now()).total_seconds() // 60) + 1
    return True, remaining


def register_failed_login(username):
    conn = get_conn()
    row = conn.execute("SELECT id, failed_attempts FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        conn.close()
        return
    attempts = row["failed_attempts"] + 1
    locked_until = None
    if attempts >= MAX_FAILED_ATTEMPTS:
        locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
        attempts = 0  # on repart à zéro une fois le verrouillage posé
    conn.execute(
        "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
        (attempts, locked_until, row["id"]),
    )
    conn.commit()
    conn.close()


def register_successful_login(username):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
        (username,),
    )
    conn.commit()
    conn.close()


def verify_user(username, password):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def change_password(user_id, new_password):
    if len(new_password) < 4:
        return False, "Mot de passe trop court (minimum 4 caractères)."
    conn = get_conn()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()
    return True, None


def verify_password(user_id, password):
    conn = get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(row and check_password_hash(row["password_hash"], password))


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, role, min_confidence, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_users():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()
    return n


def count_admins():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) as c FROM users WHERE role='admin'").fetchone()["c"]
    conn.close()
    return n


def delete_user(user_id):
    conn = get_conn()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def update_min_confidence(user_id, value):
    conn = get_conn()
    conn.execute("UPDATE users SET min_confidence = ? WHERE id = ?", (int(value), user_id))
    conn.commit()
    conn.close()


# ------------------------------------------------------------ décorateurs ----

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Non connecté."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Non connecté."}), 401
            return redirect(url_for("login_page"))
        if session.get("role") != "admin":
            return jsonify({"error": "Réservé aux administrateurs."}), 403
        return f(*args, **kwargs)
    return wrapper
