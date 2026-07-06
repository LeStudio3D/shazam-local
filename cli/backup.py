"""
backup.py
---------
Sauvegarde le contenu de db/ (base de fingerprints, comptes utilisateurs,
corrections...) dans une archive horodatée sous backups/. Ne conserve que
les N sauvegardes les plus récentes pour ne pas remplir le disque.

Usage :
    python cli/backup.py                # sauvegarde manuelle
    python cli/backup.py --keep 20      # garder les 20 dernières au lieu de 15
"""

import argparse
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

DB_DIR = Path("db")
CONFIG_PATH = Path("config.json")
BACKUP_DIR = Path("backups")
DEFAULT_KEEP = 15


def create_backup(label="manual", keep=DEFAULT_KEEP):
    if not DB_DIR.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = BACKUP_DIR / f"backup_{timestamp}_{label}.zip"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DB_DIR.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f))
        if CONFIG_PATH.exists():
            zf.write(CONFIG_PATH, arcname=str(CONFIG_PATH))

    _prune_old_backups(keep)
    return archive_path


def _prune_old_backups(keep):
    backups = sorted(BACKUP_DIR.glob("backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


def restore_backup(archive_path):
    """Restaure une sauvegarde (écrase db/ et config.json actuels)."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        print(f"Introuvable : {archive_path}")
        return False

    if DB_DIR.exists():
        safety = BACKUP_DIR / f"avant_restauration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        create_backup(label="avant_restauration")
        print(f"Sécurité : état actuel sauvegardé dans {safety.name} avant restauration.")

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(".")
    print(f"Restauré depuis {archive_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sauvegarde / restauration de la base")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="Nombre de sauvegardes à conserver")
    parser.add_argument("--restore", type=str, default=None, help="Chemin d'une archive à restaurer")
    args = parser.parse_args()

    if args.restore:
        restore_backup(args.restore)
        return

    path = create_backup(label="manual", keep=args.keep)
    if path:
        size_kb = path.stat().st_size / 1024
        print(f"Sauvegarde créée : {path} ({size_kb:.0f} Ko)")
    else:
        print("Rien à sauvegarder (dossier db/ introuvable).")


if __name__ == "__main__":
    main()
