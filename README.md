# Schazam-local — Reconnaissance musicale locale et auto-hébergée

Un "Shazam" personnel, 100% local : il identifie un morceau de musique à partir d'un extrait audio (micro du navigateur ou fichier), en le comparant à ta propre bibliothèque MP3 indexée sur ton PC. Aucune donnée audio n'est envoyée à un service tiers — tout tourne chez toi.

Basé sur le même principe algorithmique que Shazam (empreintes combinatoires de pics spectraux, popularisées par l'article d'Avery Wang en 2003) : reconnaissance robuste au bruit ambiant, invariante au décalage temporel de l'extrait.

**Fonctionnalités principales :**
- 🎧 Indexation d'une bibliothèque MP3/WAV/FLAC locale, à n'importe quelle échelle raisonnable pour un usage personnel
- 🎤 Identification via le micro du navigateur (enregistrement direct, pas besoin d'app séparée) ou en ligne de commande
- 👥 Comptes multi-utilisateurs avec rôles admin/utilisateur, mots de passe hashés, verrouillage anti brute-force
- 🎯 Auto-calibration : chaque utilisateur peut affiner son seuil de détection à partir de ses propres résultats confirmés ; l'admin peut recalibrer les paramètres d'indexation globaux
- 🧹 Détection et nettoyage des doublons entre playlists
- 📋 Revue en lot d'échantillons d'entraînement depuis l'interface d'administration
- 📊 Logs en temps réel et sauvegardes automatiques horodatées

**Stack :** Python (NumPy/SciPy pour le traitement du signal, Flask pour l'interface web), SQLite pour les comptes, aucune dépendance à un service cloud.

⚠️ Projet personnel à but éducatif, non affilié à Shazam/Apple. Respecte le droit d'auteur : cet outil est prévu pour identifier ta propre bibliothèque musicale, pas pour contourner des mesures de protection ou faciliter le partage illégal.

---

## 1. Prérequis

### Python
Vérifie que tu as Python 3.10+ :
```
python --version
```
Si tu ne l'as pas : `winget install Python.Python.3.12` (redémarre le terminal après), ou depuis python.org (coche bien "Add python.exe to PATH" à l'install).

### FFmpeg (nécessaire pour lire les MP3)
`librosa` sait décoder le MP3 via FFmpeg. Sur Windows 11, le plus simple avec winget :
```
winget install Gyan.FFmpeg
```
Redémarre ton terminal après, puis vérifie :
```
ffmpeg -version
```
Si la commande n'est pas reconnue, il faut ajouter manuellement le dossier `bin` de FFmpeg à la variable d'environnement PATH (Paramètres système > Variables d'environnement).

## 2. Installation du projet

Dézippe le projet quelque part, par exemple `C:\Users\TonNom\shazam_proto`, puis dans un terminal (PowerShell) :

```powershell
git clone https://github.com/LeStudio3D/shazam-local.git

cd shazam-local

# créer un environnement virtuel
python -m venv venv

# l'activer
venv\Scripts\activate

# installer les dépendances
pip install -r requirements.txt
```

Si PowerShell bloque l'activation du venv (erreur "execution of scripts is disabled"), lance une fois :
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Utilisation

Copie une partie de tes MP3 (deemix) dans le dossier `songs\` (sous-dossiers acceptés).

**Indexer ta bibliothèque :**
```powershell
python cli/main.py index songs
```

**Calibrer / vérifier que l'algo marche bien sur TA base** (avant de te fier aux résultats sur du bruit réel) :
```powershell
python cli/main.py selftest
```
Ça prend 8 morceaux déjà indexés au hasard, en extrait 10 secondes propres, et vérifie qu'`identify` les retrouve. Ça te donne une vraie référence de ce qu'est une "bonne" confiance sur ta bibliothèque (typiquement des dizaines à plusieurs centaines de hash alignés pour un extrait propre).

Identifier + confirmer/corriger le résultat** (recommandé pour se constituer un vrai jeu de test) :
```powershell
python cli/main.py identify "chemin\vers\extrait.mp3" --confirm
```
Après le résultat, tu peux :
- taper le numéro du bon résultat s'il est dans la liste proposée
- taper `n` puis chercher le bon morceau par son titre s'il n'est pas proposé
- laisser vide si le morceau n'est carrément pas dans ta base
- taper `s` pour passer sans rien enregistrer

Tout ça est journalisé dans `db\corrections.json`.

**Voir les stats de précision accumulées :**
```powershell
python cli/main.py stats
```

**Calibrer automatiquement les paramètres à partir de tes corrections :**
```powershell
python cli/calibrate.py
```
Teste plusieurs réglages sur un échantillon de ta bibliothèque, choisit le meilleur (précision + confiance), et l'écrit dans `config.json`. Il faut au moins 3 corrections confirmées (`--confirm`) avec un morceau correct identifié pour que ça fonctionne. **Après une calibration, il faut réindexer entièrement** (les hash changent) :
```powershell
python cli/main.py index songs --rebuild
```

Tu peux relancer `index` plusieurs fois avec de nouveaux dossiers/fichiers : les morceaux déjà indexés sont automatiquement ignorés (la base s'enrichit, elle n'est jamais écrasée) — sauf avec `--rebuild`, qui repart de zéro.

## 4. Comptes utilisateurs et rôles

**Avant le tout premier lancement de l'interface web**, crée le compte administrateur :
```powershell
python cli/create_admin.py
```
Ça te demande un nom d'utilisateur et un mot de passe (jamais stockés en clair, toujours hashés).

**Ce que voit un compte "utilisateur" simple (le reste de la famille) :**
- Onglet **Identifier** (enregistrement micro)
- Onglet **Réglages** : uniquement SON seuil de confiance personnel, réglable à la main ou via un bouton **"Calibrer automatiquement"** qui teste plusieurs seuils à partir de ses propres recherches déjà confirmées (il en faut au moins 3) et garde le meilleur.

**Ce que voit en plus un compte "administrateur" (toi) :**
- **Comptes** : créer/supprimer des comptes utilisateurs (impossible de supprimer le dernier admin)
- **Entraînement** : dépose des extraits de ~10s dans le dossier `training/`, ils sont proposés un par un dans l'interface pour être confirmés/corrigés, sans jamais avoir à relancer une commande
- **Réglages avancés** : les paramètres d'indexation globaux (partagés par tout le monde, car ils déterminent comment la base entière est construite) + le bouton de calibration automatique globale
- **Logs** : flux temps réel de toute l'activité (recherches de tous les utilisateurs, erreurs, connexions...)

**Pourquoi le seuil de confiance est le SEUL réglage "par utilisateur" :** les autres paramètres (seuil d'amplitude, voisinage, fan-out...) déterminent comment les hash sont calculés et stockés dans la base **partagée**. Si un utilisateur les changeait pour lui-même, ses recherches ne correspondraient plus à rien dans l'index (qui a été construit avec d'autres valeurs). Le seuil de confiance, lui, ne s'applique qu'au moment de la recherche — il peut donc être différent pour chacun sans rien casser.

**Le CLI (`cli/main.py`, `cli/dedup.py`, `cli/calibrate.py`) reste indépendant des comptes web** — il continue de fonctionner directement en local, les corrections faites via `identify --confirm` sont juste taguées avec ton nom d'utilisateur Windows (ex : `cli:Collaborateur`) pour les distinguer dans `python cli/main.py stats`.

## 5. Interface web (enregistrement micro, logs temps réel, réglages)

Une fois que ta base est indexée (`python cli/main.py index songs`), lance :
```powershell
python web/webapp.py
```

Puis ouvre dans un navigateur :
- **`http://localhost:5000`** — depuis ce PC
- **`http://<ton-ip-locale>:5000`** — depuis un autre appareil du même réseau (téléphone, autre PC).
  Pour trouver ton IP locale : `ipconfig` dans PowerShell, cherche "Adresse IPv4" (souvent `192.168.1.x`).

**⚠️ Micro dans le navigateur :** l'accès au micro (`getUserMedia`) n'est autorisé par les navigateurs que sur `localhost` ou en HTTPS. Donc :
- Sur le PC lui-même (`localhost:5000`) : le micro marche directement.
- Depuis un **autre appareil** via l'IP locale (`192.168.1.x:5000`) : la plupart des navigateurs **bloqueront le micro** car ce n'est pas une connexion sécurisée (pas de HTTPS). L'interface reste consultable (logs, réglages), mais pour enregistrer depuis un téléphone il faudra soit mettre en place un certificat HTTPS auto-signé plus tard, soit enregistrer sur le PC lui-même pour l'instant.

**Trois onglets :**
- **Identifier** : bouton d'enregistrement (10 secondes), résultats avec possibilité de confirmer le bon morceau ou d'en chercher un autre par titre (alimente `corrections.json`)
- **Logs** : flux temps réel de tout ce qui se passe côté serveur (recherches, résultats, erreurs, corrections)
- **Réglages** : modifier les paramètres de l'algo (seuil d'amplitude, voisinage, fan-out...) sans toucher au code, + bouton pour lancer la calibration automatique

**Important :** changer les réglages (manuellement ou via calibration) modifie `config.json`. Il faut ensuite **redémarrer `web/webapp.py`** (pour recharger la config) puis, dans un terminal séparé, lancer `python cli/main.py index songs --rebuild` pour réindexer avec les nouveaux paramètres.

## 6. Sécurité des comptes

- **Changer son propre mot de passe** : onglet Réglages, en bas, pour tout le monde (demande l'ancien mot de passe).
- **Réinitialiser le mot de passe de quelqu'un** : onglet Comptes (admin), bouton "Réinitialiser mdp" à côté de chaque utilisateur — utile si quelqu'un de la famille oublie le sien.
- **Anti brute-force** : après 5 échecs de connexion sur un même compte, celui-ci est verrouillé 15 minutes (même avec le bon mot de passe entre-temps). Ça se réinitialise automatiquement après une connexion réussie.

## 7. Confort : surveillance automatique et sauvegardes

**Surveillance du dossier `songs/`** : tant que `web/webapp.py` tourne, un nouveau fichier déposé dans `songs/` (ou un sous-dossier) est automatiquement détecté et indexé toutes les 5 minutes, sans avoir besoin de relancer `python cli/main.py index` à la main. Ça se voit dans les logs (admin) :
```
Surveillance : 1 nouveau(x) fichier(s) détecté(s) dans songs/, indexation...
Surveillance : indexation automatique terminée (1 ajout(s)).
```

**Sauvegardes automatiques** : une sauvegarde horodatée de `db/` (base, comptes, corrections) est créée automatiquement :
- à chaque démarrage de `web/webapp.py`
- avant un `python cli/main.py index songs --rebuild`
- avant que `cli/dedup.py` n'applique des suppressions
- avant que `cli/calibrate.py` n'écrive une nouvelle configuration

Les sauvegardes s'accumulent dans `backups/` (15 dernières conservées, les plus anciennes sont supprimées automatiquement). Sauvegarde manuelle à tout moment :
```powershell
python cli/backup.py
```
Restauration (attention, ça écrase l'état actuel — une sauvegarde de sécurité de l'état actuel est prise automatiquement avant) :
```powershell
python cli/backup.py --restore backups/backup_20260704_120000_manual.zip
```

## 8. Structure du projet

```
shazam_proto/
├── src/                   # Algorithme et logique métier (réutilisés par cli/ et web/)
│   ├── fingerprint.py     # l'algo pur : spectrogramme, pics, hash (lit config.json si présent)
│   ├── database.py        # chargement audio + indexation + sauvegarde/recherche
│   ├── feedback.py         # journal de corrections (tagué par utilisateur)
│   ├── user_calibration.py # calibration légère du seuil perso (query-time uniquement)
│   ├── auth.py               # comptes utilisateurs (SQLite), hashing, verrouillage, décorateurs de rôle
│   ├── training.py           # file d'attente des échantillons dans training/
│   └── logs.py              # journal centralisé (admin uniquement)
├── cli/                   # Outils à lancer en ligne de commande
│   ├── main.py             # index / identify / selftest / stats
│   ├── calibrate.py        # (admin) auto-régle les paramètres d'indexation globaux
│   ├── dedup.py             # détecte et résout les doublons entre playlists
│   ├── create_admin.py       # bootstrap : crée le 1er compte administrateur
│   └── backup.py             # sauvegarde/restauration horodatée de db/
├── web/                   # Interface web (Flask)
│   ├── webapp.py            # micro, comptes, admin
│   ├── templates/
│   │   ├── login.html
│   │   └── index.html
│   └── static/
│       ├── style.css
│       └── app.js
├── config.json          # généré par cli/calibrate.py ou réglages avancés (admin)
├── requirements.txt
├── .gitignore
├── songs/              # -> mets tes mp3 ici
├── training/             # -> dépose les échantillons de ~10s à revoir (admin)
├── backups/              # sauvegardes horodatées automatiques
└── db/
    ├── users.db            # comptes (mots de passe hashés)
    ├── secret.key           # clé de session Flask (générée automatiquement)
    ├── fingerprints.pkl   # généré automatiquement à la 1ère indexation
    ├── corrections.json   # journal de corrections, tagué par utilisateur
    ├── training_reviewed.json  # suivi de ce qui a déjà été revu dans training/
    └── app.log             # journal texte de l'interface web
```

**Important : toutes les commandes se lancent depuis la racine du projet** (`shazam_proto/`), jamais depuis l'intérieur de `cli/` ou `web/` — c'est ce qui permet aux chemins relatifs (`db/`, `songs/`, `config.json`...) de toujours pointer au bon endroit.

