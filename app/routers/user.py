import logging
import time

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Site, SiteStatus
from app.validators import SLUG_RE as _SLUG_RE

_log = logging.getLogger("monminilab.user")

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Cache JWKS en mémoire (refresh toutes les heures)
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}
_JWKS_TTL = 3600


def _get_cf_public_keys() -> list:
    now = time.monotonic()
    if now - _jwks_cache["fetched_at"] < _JWKS_TTL and _jwks_cache["keys"]:
        return _jwks_cache["keys"]
    url = f"https://{settings.CF_TEAM_DOMAIN}.cloudflareaccess.com/cdn-cgi/access/certs"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return keys
    except Exception as e:
        _log.error("Impossible de recuperer les cles JWKS CF Access : %s", e)
        return _jwks_cache["keys"]


def _verify_cf_jwt(token: str) -> dict | None:
    keys = _get_cf_public_keys()
    if not keys:
        _log.error("JWKS CF Access vide — impossible de valider le JWT")
        return None

    # Sélection de la clé par kid pour éviter d'essayer toutes les clés inutilement
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        keys_to_try = [k for k in keys if k.get("kid") == kid] if kid else keys
        if not keys_to_try:
            keys_to_try = keys
    except Exception:
        keys_to_try = keys

    issuer = f"https://{settings.CF_TEAM_DOMAIN}.cloudflareaccess.com"
    for key in keys_to_try:
        try:
            public_key = RSAAlgorithm.from_jwk(key)
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=settings.CF_ACCESS_AUD,
                issuer=issuer,
            )
            return payload
        except Exception:
            continue
    return None


def _get_site_from_cf(request: Request, db: Session):
    token = request.headers.get("Cf-Access-Jwt-Assertion", "")
    if not token:
        _log.warning("Acces /my sans Cf-Access-Jwt-Assertion — ip=%s",
                     request.client.host if request.client else "?")
        return None

    payload = _verify_cf_jwt(token)
    if not payload:
        _log.warning("JWT CF Access invalide — ip=%s",
                     request.client.host if request.client else "?")
        return None

    # L'email vient du payload JWT vérifié, pas d'un header forgeable
    cf_email = payload.get("email", "")
    if not cf_email.endswith(f"@{settings.BASE_DOMAIN}"):
        return None

    slug = cf_email.split("@")[0]
    if not _SLUG_RE.match(slug):
        return None

    site = db.query(Site).filter(Site.slug == slug, Site.status == SiteStatus.ready).first()
    if not site:
        return None

    # Défense contre IDOR : l'identité CF Access doit correspondre à client_cf_email.
    # Pour les sites anciens (client_cf_email null), fallback sur le comportement historique.
    if site.client_cf_email is not None and cf_email != site.client_cf_email:
        _log.warning("IDOR potentiel : email CF %s ne correspond pas au site %s", cf_email, slug)
        return None

    return site


@router.get("/my", response_class=HTMLResponse)
async def user_dashboard(request: Request, db: Session = Depends(get_db)):
    site = _get_site_from_cf(request, db)
    if not site:
        return templates.TemplateResponse(request, "user/not_authenticated.html", {})

    site_url = f"https://{site.slug}.{settings.BASE_DOMAIN}"

    return templates.TemplateResponse(
        request,
        "user/dashboard.html",
        {
            "site": site,
            "site_url": site_url,
            "wp_admin_url": f"{site_url}/wp-admin",
            "wp_lostpassword_url": f"{site_url}/wp-login.php?action=lostpassword",
            "smtp_user": f"{site.slug}@{settings.BASE_DOMAIN}",
        },
    )
