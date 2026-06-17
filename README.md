# MonMiniLab Admin

Plateforme d'hébergement WordPress mutualisé self-hosted. Crée et provisionne automatiquement un site WordPress complet en quelques minutes, sans aucune intervention manuelle.

## Fonctionnement

```
Admin remplit slug + email client
         │
         ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  1. MariaDB       Création base de données et user dédié    │
  │  2. ForwardEmail  Alias slug@votre-domaine.fr → email client│
  │  3. SMTP          Génération mot de passe SMTP              │
  │  4. Docker        Lancement container WordPress (128 MB)    │
  │  5. Attente       WordPress prêt à répondre (max 5 min)     │
  │  6. wp-cli        wp core install (pas de wizard)           │
  │  7. Cloudflare    Ingress tunnel + CNAME DNS                │
  │  8. Email         Bienvenue avec accès → client             │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  https://slug.votre-domaine.fr  ✓  en ligne
```

Le provisionnement tourne en **tâche de fond** — le browser peut se déconnecter sans interrompre le processus. L'état est récupérable via polling. Les logs détaillés de chaque étape sont accessibles dans l'interface admin.

## Accès

| Interface | URL | Auth |
|-----------|-----|------|
| Dashboard admin | `https://admin.votre-domaine.fr` | Cloudflare Access + mot de passe |
| Portail client | `https://portail.votre-domaine.fr` | Cloudflare Access (`@votre-domaine.fr`) |
| API REST | `https://admin.votre-domaine.fr/api` | Bearer JWT |
| Swagger UI | `https://admin.votre-domaine.fr/api/docs` | Bearer JWT |

## Stack technique

- **Backend** — FastAPI + SQLAlchemy + SQLite
- **Frontend** — Jinja2 + CSS custom (dark, Syne + JetBrains Mono)
- **Containers** — Docker SDK Python, image WordPress custom (limite 128 MB RAM)
- **DNS/Tunnel** — Cloudflare Zero Trust (remote-managed, 100% API)
- **Email** — ForwardEmail (alias + SMTP)
- **Auth admin** — Cloudflare Access + cookie de session JWT (`SameSite=Strict`, HTTPS)
- **Auth client** — Cloudflare Access header injection + vérification `Cf-Access-Jwt-Assertion`
- **Updates** — Watchtower désactivé : pull manuel après chaque push GitHub
- **Ressources** — MariaDB limité à 512 MB RAM, chaque WP à 128 MB

## Sécurité

### Architecture

L'application est accessible **uniquement via le tunnel Cloudflare Zero Trust**. Les ports ne sont pas exposés publiquement. Les containers WordPress écoutent sur `127.0.0.1:{port}` (loopback hôte uniquement).

### Authentification

| Surface | Mécanisme |
|---------|-----------|
| Dashboard admin | Cookie session `SameSite=Strict` + `Secure` + vérification mot de passe (bcrypt ou `secrets.compare_digest`) |
| API REST | Bearer JWT signé, durée 1h |
| Portail client `/my` | Validation cryptographique RS256 du JWT `Cf-Access-Jwt-Assertion` (JWKS, audience, issuer, expiry) + email `@votre-domaine.fr` extrait du payload vérifié |

### Validation des entrées

- **Slugs** : regex `^[a-z0-9][a-z0-9\-]{1,28}[a-z0-9]$` appliquée à toutes les routes (`Path(pattern=...)`) et dans chaque service (défense en profondeur)
- **Slugs réservés** : liste de ~30 slugs bloqués (`admin`, `portail`, `www`, `mail`, `api`, etc.)
- **Email** : validé via `email-validator` (format + normalisation)
- **Mots de passe** : `max_length=128` sur tous les champs
- **WP-CLI** : exécuté en liste d'arguments — aucun `bash -c`, aucune interpolation shell

### CSRF

Cookie de session `SameSite=Strict` — les requêtes cross-site ne transportent pas le cookie. Toutes les routes POST destructives requièrent une session admin active.

## Déploiement

### Prérequis

- Docker + Docker Compose
- Cloudflare tunnel remote-managed configuré sur le domaine
- Compte ForwardEmail avec domaine vérifié

### Installation

#### 1. Préparer le répertoire de données

Le container app tourne en utilisateur non-root (UID 1001, GID 989). Il faut créer le répertoire de données et lui donner les bons droits **avant** le premier démarrage.

```bash
# UID 1001 = utilisateur app dans le container
# GID 989  = groupe docker sur l'hôte (vérifier avec : stat -c "%g" /var/run/docker.sock)
sudo mkdir -p /path/to/data
sudo chown -R 1001:989 /path/to/data
```

> Si le GID du socket Docker est différent de 989 sur votre machine, adaptez le `groupadd --gid` dans le `Dockerfile` et reconstruisez l'image.

#### 2. Cloner et configurer

```bash
git clone https://github.com/your-org/monminilab-admin
cd monminilab-admin
cp .env.example .env
# Remplir .env (voir section Variables d'environnement)
```

#### 3. Démarrer

```bash
sudo docker compose up -d
sudo docker logs monminilab-admin --tail 20
```

Au démarrage, l'app vérifie que `SECRET_KEY` est définie et non vide — elle refuse de démarrer si c'est la valeur par défaut.

### Mise à jour

Après chaque push sur `main`, attendre la fin du build CI puis :

```bash
sudo docker compose pull app
sudo docker compose up -d app
```

### Variables d'environnement

```env
# Auth
ADMIN_PASSWORD=         # Hash bcrypt recommandé
SECRET_KEY=             # Clé longue et aléatoire (min 32 chars)

# MariaDB
MARIADB_ROOT_PASSWORD=

# Cloudflare
CF_TOKEN=               # Bearer token (tunnels/DNS)
CF_GLOBAL_API_KEY=
CF_ACCOUNT_EMAIL=
CF_ACCOUNT_ID=
CF_ZONE_ID=
CF_TUNNEL_ID=

# ForwardEmail
FE_API_KEY=

# Cloudflare Access (portail client)
CF_TEAM_DOMAIN=             # sous-domaine de cloudflareaccess.com (ex: monequipe)
CF_ACCESS_AUD=              # Application ID de l'app CF Access portail

# Domaine de base
BASE_DOMAIN=votre-domaine.fr
```

### Générer un hash bcrypt pour ADMIN_PASSWORD

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'votre-mot-de-passe', bcrypt.gensalt()).decode())"
```

### Générer une SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## API REST

### Authentification

```bash
curl -X POST https://admin.votre-domaine.fr/api/token \
  -H "Content-Type: application/json" \
  -d '{"password": "votre-mot-de-passe"}'
# -> { "access_token": "eyJ...", "token_type": "bearer" }
```

Toutes les routes suivantes requièrent `Authorization: Bearer <token>`.

### Sites

```bash
GET    /api/sites
POST   /api/sites           { "slug": "...", "client_email": "..." }
GET    /api/sites/{slug}
GET    /api/sites/{slug}/status
PATCH  /api/sites/{slug}    { "client_email": "..." }
DELETE /api/sites/{slug}
```

## Structure du projet

```
app/
├── main.py                  # FastAPI app, middlewares, routers
├── config.py                # Settings Pydantic (.env)
├── models.py                # SQLAlchemy — Site
├── auth.py                  # JWT, require_admin, require_api_token
├── validators.py            # Regex slug + liste réservés (partagés)
├── limiter.py               # Rate limiter (CF-Connecting-IP)
├── database.py              # SQLite init
├── routers/
│   ├── admin.py             # Dashboard + provisionnement + logs
│   ├── user.py              # Portail client (auth CF Access JWT JWKS)
│   └── api.py               # REST API
├── services/
│   ├── docker_service.py    # Docker SDK — create/remove/exec/logs
│   ├── mariadb_service.py   # DB + user MariaDB
│   ├── cloudflare_service.py# Tunnel ingress + DNS CNAME
│   ├── forwardemail_service.py
│   └── mail_service.py      # Email de bienvenue
└── templates/
    ├── base.html            # Layout dark, Syne, skip link, sr-only
    ├── login.html
    ├── admin/
    │   ├── dashboard.html
    │   ├── create.html      # Provisionnement + logs live
    │   └── logs.html        # Viewer logs (site ou app)
    └── user/
        ├── dashboard.html
        └── not_authenticated.html
```

## Données persistantes

| Variable / Chemin | Contenu |
|-------------------|---------|
| `DB_PATH` (défaut `/data/app.db`) | SQLite — sites |
| Volume MariaDB | Données MariaDB (512 MB RAM) |
| `SITES_DATA_DIR/{slug}/` | Fichiers WordPress (128 MB RAM par container) |
