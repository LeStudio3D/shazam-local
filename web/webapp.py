"""
webapp.py
---------
Interface web du prototype Shazam-like, avec comptes utilisateurs.

Avant le premier lancement :
    python cli/create_admin.py

Lancement :
    python web/webapp.py

Accessible sur :
    http://localhost:5000
    http://<ton-ip-locale>:5000
"""

import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cli"))

from flask import Flask, request, jsonify, render_template, Response, stream_with_context, session, redirect, url_for

from database import FingerprintDB
import database
import feedback
import logs
import auth
import training
import user_calibration
import backup
from auth import login_required, admin_required

app = Flask(__name__)

SECRET_KEY_PATH = Path("db/secret.key")
SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
if not SECRET_KEY_PATH.exists():
    SECRET_KEY_PATH.write_text(secrets.token_hex(32))
app.secret_key = SECRET_KEY_PATH.read_text().strip()

DB_PATH = Path("db/fingerprints.pkl")
CONFIG_PATH = Path("config.json")

DEFAULT_INDEX_SETTINGS = {
    "amp_min_db": -40,
    "neighborhood": [20, 20],
    "fan_out": 5,
    "time_window": 100,
    "min_confidence": 3,
}

_db = None
_db_lock = threading.Lock()

auth.init_db()


def get_db():
    global _db
    with _db_lock:
        if _db is None:
            if DB_PATH.exists():
                _db = FingerprintDB.load(DB_PATH)
                logs.log(f"Base chargée : {len(_db.songs)} morceaux, {len(_db.hash_index)} hash")
            else:
                _db = FingerprintDB()
                logs.log("Aucune base trouvée pour l'instant (index à faire en CLI d'abord).", level="WARN")
        return _db


def reload_db():
    global _db
    with _db_lock:
        _db = None
    return get_db()


def current_user():
    uid = session.get("user_id")
    return auth.get_user(uid) if uid else None


# ---------------------------------------------------------------- pages ----

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("index"))
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    locked, minutes = auth.check_lockout(username)
    if locked:
        logs.log(f"Tentative de connexion bloquée (compte verrouillé) : {username}", level="WARN")
        return render_template("login.html", error=f"Compte temporairement verrouillé. Réessaie dans {minutes} minute(s).")

    user = auth.verify_user(username, password)
    if not user:
        auth.register_failed_login(username)
        logs.log(f"Échec de connexion : {username}", level="WARN")
        return render_template("login.html", error="Identifiants incorrects.")

    auth.register_successful_login(username)
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    logs.log(f"Connexion : {user['username']} ({user['role']})")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    if "username" in session:
        logs.log(f"Déconnexion : {session['username']}")
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def index():
    user = current_user()
    return render_template("index.html", username=user["username"], role=user["role"])


# ------------------------------------------------------------- identify ----

@app.route("/api/status")
@login_required
def api_status():
    db = get_db()
    return jsonify({"songs": len(db.songs), "hashes": len(db.hash_index), "username": session["username"], "role": session["role"]})


@app.route("/api/identify", methods=["POST"])
@login_required
def api_identify():
    if "audio" not in request.files:
        return jsonify({"error": "Aucun fichier audio reçu."}), 400

    user = current_user()
    audio_file = request.files["audio"]
    suffix = Path(audio_file.filename or "clip.webm").suffix or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name

        logs.log(f"Recherche de {user['username']} depuis le navigateur ({suffix}).")
        db = get_db()
        min_conf = user["min_confidence"]
        results = db.identify(tmp_path, top_n=5, min_confidence=min_conf)

        if results:
            top = results[0]
            logs.log(f"Résultat pour {user['username']} : '{top[1]}' (confiance={top[2]}, début={top[3]:.1f}s)")
        else:
            logs.log(f"Aucun match trouvé pour {user['username']}.", level="WARN")

        return jsonify({
            "results": [
                {"song_id": sid, "title": title, "confidence": conf, "offset_sec": round(offset, 1)}
                for sid, title, conf, offset in results
            ]
        })
    except Exception as e:
        logs.log(f"Erreur pendant l'identification ({user['username']}) : {e}", level="ERROR")
        return jsonify({"error": str(e)}), 500
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# --------------------------------------------------------------- confirm ----

@app.route("/api/search_songs")
@login_required
def api_search_songs():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"matches": []})
    db = get_db()
    matches = db.search_by_title(q)[:20]
    return jsonify({"matches": [{"song_id": sid, "title": t} for sid, t in matches]})


@app.route("/api/confirm", methods=["POST"])
@login_required
def api_confirm():
    data = request.get_json(force=True)
    feedback.record_correction(
        query_file=data.get("query_label", "web-recording"),
        predicted_song_id=data.get("predicted_song_id"),
        predicted_title=data.get("predicted_title"),
        confidence=data.get("confidence", 0),
        correct_song_id=data.get("correct_song_id"),
        correct_title=data.get("correct_title", "(absent de la base)"),
        was_correct=bool(data.get("was_correct", False)),
        username=session["username"],
    )
    logs.log(f"Correction enregistrée par {session['username']} : '{data.get('correct_title')}'.")
    return jsonify({"ok": True})


# ------------------------------------------------------- réglages perso ----

@app.route("/api/user/settings", methods=["GET"])
@login_required
def api_user_settings_get():
    user = current_user()
    return jsonify({"min_confidence": user["min_confidence"]})


@app.route("/api/user/settings", methods=["POST"])
@login_required
def api_user_settings_post():
    data = request.get_json(force=True)
    value = int(data.get("min_confidence", 3))
    value = max(1, min(value, 999))
    auth.update_min_confidence(session["user_id"], value)
    logs.log(f"{session['username']} a réglé son seuil de confiance à {value}.")
    return jsonify({"ok": True})


@app.route("/api/user/auto_calibrate", methods=["POST"])
@login_required
def api_user_auto_calibrate():
    username = session["username"]
    best_t, n, accuracy = user_calibration.compute_best_threshold(username)
    if accuracy is None:
        return jsonify({
            "ok": False,
            "message": f"Pas assez de données pour calibrer (seulement {n} recherche(s) confirmée(s), il en faut au moins 3). "
                       f"Utilise la recherche normale avec confirmation quelques fois d'abord."
        })
    auth.update_min_confidence(session["user_id"], best_t)
    logs.log(f"Auto-calibration de {username} : seuil = {best_t} (sur {n} exemples, {accuracy}% de cohérence).")
    return jsonify({
        "ok": True,
        "min_confidence": best_t,
        "n_examples": n,
        "accuracy": accuracy,
        "message": f"Seuil réglé à {best_t} à partir de {n} recherche(s) confirmée(s) (cohérence estimée {accuracy}%)."
    })


@app.route("/api/user/change_password", methods=["POST"])
@login_required
def api_user_change_password():
    data = request.get_json(force=True)
    current = data.get("current_password", "")
    new = data.get("new_password", "")

    if not auth.verify_password(session["user_id"], current):
        return jsonify({"ok": False, "error": "Mot de passe actuel incorrect."}), 400

    ok, err = auth.change_password(session["user_id"], new)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    logs.log(f"{session['username']} a changé son mot de passe.")
    return jsonify({"ok": True})


# ---------------------------------------------------------- admin: users ----

@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_list_users():
    return jsonify({"users": auth.list_users()})


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    if role not in ("user", "admin"):
        role = "user"
    if len(password) < 4:
        return jsonify({"ok": False, "error": "Mot de passe trop court (minimum 4 caractères)."}), 400
    ok, err = auth.create_user(username, password, role)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    logs.log(f"{session['username']} a créé le compte '{username}' (rôle: {role}).")
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>/reset_password", methods=["POST"])
@admin_required
def api_admin_reset_password(user_id):
    target = auth.get_user(user_id)
    if not target:
        return jsonify({"ok": False, "error": "Utilisateur introuvable."}), 404
    data = request.get_json(force=True)
    new_password = data.get("new_password", "")
    ok, err = auth.change_password(user_id, new_password)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    logs.log(f"{session['username']} a réinitialisé le mot de passe de '{target['username']}'.")
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@admin_required
def api_admin_delete_user(user_id):
    target = auth.get_user(user_id)
    if not target:
        return jsonify({"ok": False, "error": "Utilisateur introuvable."}), 404
    if target["role"] == "admin" and auth.count_admins() <= 1:
        return jsonify({"ok": False, "error": "Impossible de supprimer le dernier compte administrateur."}), 400
    auth.delete_user(user_id)
    logs.log(f"{session['username']} a supprimé le compte '{target['username']}'.")
    if user_id == session.get("user_id"):
        session.clear()
    return jsonify({"ok": True})


# ------------------------------------------------------- admin: réglages ----

@app.route("/api/admin/settings", methods=["GET"])
@admin_required
def api_admin_get_settings():
    cfg = dict(DEFAULT_INDEX_SETTINGS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return jsonify(cfg)


@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def api_admin_save_settings():
    data = request.get_json(force=True)
    cfg = dict(DEFAULT_INDEX_SETTINGS)
    cfg.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    logs.log(f"{session['username']} a mis à jour les réglages d'indexation globaux : {cfg}")
    return jsonify({
        "ok": True,
        "note": "Réglages sauvegardés. Redémarre web/webapp.py puis lance 'python cli/main.py index songs --rebuild' pour les appliquer."
    })


@app.route("/api/admin/calibrate", methods=["POST"])
@admin_required
def api_admin_calibrate():
    admin_name = session["username"]

    def run():
        logs.log(f"Calibration automatique lancée par {admin_name} (détail dans la console serveur)...")
        try:
            import calibrate
            calibrate.main()
            logs.log("Calibration terminée. Redémarre web/webapp.py puis lance 'index --rebuild'.")
        except Exception as e:
            logs.log(f"Erreur pendant la calibration : {e}", level="ERROR")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "note": "Calibration lancée en arrière-plan (admin uniquement)."})


# ------------------------------------------------------------ admin: logs ----

@app.route("/api/admin/logs/history")
@admin_required
def api_admin_logs_history():
    return jsonify({"logs": logs.get_all()})


@app.route("/api/admin/logs/stream")
@admin_required
def api_admin_logs_stream():
    def gen():
        last_id = int(request.args.get("since", 0))
        yield ": connected\n\n"
        while True:
            new_entries = logs.get_since(last_id)
            for entry in new_entries:
                last_id = entry["id"]
                yield f"data: {json.dumps(entry)}\n\n"
            time.sleep(1)

    return Response(stream_with_context(gen()), mimetype="text/event-stream")


# -------------------------------------------------------- admin: training ----

@app.route("/api/admin/training/status")
@admin_required
def api_admin_training_status():
    return jsonify(training.queue_status())


@app.route("/api/admin/training/next")
@admin_required
def api_admin_training_next():
    nxt = training.next_unreviewed()
    if nxt is None:
        return jsonify({"done": True})

    path, rel = nxt
    db = get_db()
    try:
        results = db.identify(str(path), top_n=5, min_confidence=1)
    except Exception as e:
        logs.log(f"Erreur en entraînement sur '{rel}' : {e}", level="ERROR")
        return jsonify({"done": False, "file": rel, "error": str(e), "results": []})

    logs.log(f"Entraînement : analyse de '{rel}'.")
    return jsonify({
        "done": False,
        "file": rel,
        "results": [
            {"song_id": sid, "title": title, "confidence": conf, "offset_sec": round(offset, 1)}
            for sid, title, conf, offset in results
        ]
    })


@app.route("/api/admin/training/confirm", methods=["POST"])
@admin_required
def api_admin_training_confirm():
    data = request.get_json(force=True)
    rel = data.get("file")
    if not rel:
        return jsonify({"ok": False, "error": "Fichier manquant."}), 400

    feedback.record_correction(
        query_file=str(training.TRAINING_DIR / rel),
        predicted_song_id=data.get("predicted_song_id"),
        predicted_title=data.get("predicted_title"),
        confidence=data.get("confidence", 0),
        correct_song_id=data.get("correct_song_id"),
        correct_title=data.get("correct_title", "(absent de la base)"),
        was_correct=bool(data.get("was_correct", False)),
        username=session["username"],
    )
    training.mark_reviewed(rel)
    logs.log(f"Entraînement : '{rel}' confirmé par {session['username']} -> '{data.get('correct_title')}'.")
    return jsonify({"ok": True})


SONGS_DIR = Path("songs")
WATCH_INTERVAL_SECONDS = 300  # 5 minutes


def watch_songs_folder():
    """Vérifie périodiquement s'il y a de nouveaux fichiers audio dans songs/
    et les indexe automatiquement (les fichiers déjà indexés sont ignorés)."""
    while True:
        time.sleep(WATCH_INTERVAL_SECONDS)
        try:
            if not SONGS_DIR.exists():
                continue
            db = get_db()
            known_paths = {info["path"] for info in db.songs.values()}
            files = [p for p in SONGS_DIR.rglob("*") if p.suffix.lower() in database.AUDIO_EXTENSIONS]
            new_files = [f for f in files if str(f) not in known_paths]
            if not new_files:
                continue

            logs.log(f"Surveillance : {len(new_files)} nouveau(x) fichier(s) détecté(s) dans songs/, indexation...")
            with _db_lock:
                for f in new_files:
                    try:
                        db.add_song(f, verbose=False)
                    except Exception as e:
                        logs.log(f"Erreur d'indexation automatique de '{f.name}' : {e}", level="ERROR")
                db.save(DB_PATH)
            logs.log(f"Surveillance : indexation automatique terminée ({len(new_files)} ajout(s)).")
        except Exception as e:
            logs.log(f"Erreur de surveillance du dossier songs/ : {e}", level="ERROR")


if __name__ == "__main__":
    if auth.count_users() == 0:
        print("Aucun compte utilisateur trouvé.")
        print("Lance d'abord : python cli/create_admin.py")
    logs.log("Démarrage du serveur web.")
    backup.create_backup("startup")
    threading.Thread(target=watch_songs_folder, daemon=True).start()
    print("Interface disponible sur :")
    print("  http://localhost:5000")
    print("  http://<ton-ip-locale>:5000   (depuis un autre appareil du réseau)")
    print(f"Surveillance automatique de songs/ activée (toutes les {WATCH_INTERVAL_SECONDS // 60} min).")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
