"""
REST API — authentification par Bearer JWT.

Obtenir un token :
  POST /api/token   { "password": "..." }  ->  { "access_token": "...", "token_type": "bearer" }

Toutes les autres routes requièrent :
  Authorization: Bearer <token>

Swagger UI disponible sur /api/docs
"""
import asyncio
import logging
import secrets
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth import create_access_token, require_api_token
from app.config import settings
from app.database import SessionLocal, get_db
from app.limiter import limiter
from app.models import Site, SiteStatus
from app.services import docker_service
from app.validators import RESERVED_SLUGS, SLUG_RE

_log = logging.getLogger("monminilab.api")

router = APIRouter(prefix="/api", tags=["API"])


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    password: str = Field(..., max_length=128)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SiteCreate(BaseModel):
    slug: str
    client_email: EmailStr

class SiteUpdate(BaseModel):
    client_email: Optional[EmailStr] = None

class SiteOut(BaseModel):
    slug: str
    status: str
    client_email: str
    url: str
    container_status: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/token", response_model=TokenResponse, summary="Obtenir un token JWT")
@limiter.limit("5/minute")
async def api_token(request: Request, body: TokenRequest):
    if not settings.verify_admin_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mot de passe incorrect")
    token = create_access_token({"sub": "admin"}, timedelta(hours=24))
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Sites — CRUD
# ---------------------------------------------------------------------------

@router.get("/sites", response_model=List[SiteOut], summary="Lister tous les sites")
async def list_sites(db: Session = Depends(get_db), _=Depends(require_api_token)):
    sites = db.query(Site).order_by(Site.created_at.desc()).all()
    return [_site_out(s) for s in sites]


@router.post("/sites", status_code=202, summary="Créer et provisionner un site")
async def create_site(body: SiteCreate, _=Depends(require_api_token)):
    from app.routers.admin import JOBS, _provision_lock, _run_provisioning
    from sqlalchemy.exc import IntegrityError

    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=422, detail="Slug invalide (3-30 chars alphanumeriques/tirets)")
    if slug in RESERVED_SLUGS:
        raise HTTPException(status_code=422, detail=f"Le slug '{slug}' est reserve")

    async with _provision_lock:
        db = SessionLocal()
        try:
            if db.query(Site).filter(Site.slug == slug).first():
                raise HTTPException(status_code=409, detail=f"Le slug '{slug}' est deja utilise")
            last_port = db.query(Site.port).order_by(Site.port.desc()).first()
            port = (last_port[0] + 1) if last_port else settings.PORT_START
            site = Site(
                slug=slug,
                port=port,
                client_email=str(body.client_email),
                client_cf_email=f"{slug}@{settings.BASE_DOMAIN}",
                status=SiteStatus.creating,
            )
            db.add(site)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(status_code=409, detail="Conflit lors de la creation (slug ou port deja utilise)")
        finally:
            db.close()

        JOBS[slug] = {
            "steps": {n: "pending" for n in range(1, 9)},
            "labels": {
                1: "Base de données MariaDB",
                2: f"Alias email {slug}@{settings.BASE_DOMAIN}",
                3: "Mot de passe SMTP ForwardEmail",
                4: "Création container WordPress",
                5: "Démarrage WordPress…",
                6: "Installation WordPress",
                7: "Tunnel Cloudflare + DNS",
                8: "Envoi email de bienvenue",
            },
            "done": False,
            "error": None,
            "url": None,
            "log": [],
        }
    asyncio.create_task(_run_provisioning(slug, str(body.client_email), port))
    return {"slug": slug, "status": "provisioning", "status_url": f"/api/sites/{slug}/status"}


_SLUG_PATH = Path(..., pattern=SLUG_RE.pattern)


@router.get("/sites/{slug}", response_model=SiteOut, summary="Détails d'un site")
async def get_site(slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    return _site_out(site)


@router.get("/sites/{slug}/status", summary="État du provisionnement")
async def site_status(slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    from app.routers.admin import JOBS
    if slug in JOBS:
        return JOBS[slug]
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    if site.status == SiteStatus.ready:
        return {"done": True, "error": None, "url": f"https://{slug}.{settings.BASE_DOMAIN}",
                "steps": {n: "done" for n in range(1, 9)}, "labels": {}}
    return {"done": False, "error": site.status, "steps": {}, "labels": {}}


@router.patch("/sites/{slug}", response_model=SiteOut, summary="Modifier un site")
async def update_site(body: SiteUpdate, slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    if body.client_email:
        site.client_email = str(body.client_email)
        db.commit()
    return _site_out(site)


@router.delete("/sites/{slug}", status_code=204, summary="Supprimer un site")
async def delete_site(slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    from app.routers.admin import teardown_site
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    await teardown_site(slug, db)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.post("/sites/{slug}/reset-wp-password", summary="Réinitialiser le mot de passe WP admin")
async def reset_wp_password(slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    new_pass = secrets.token_urlsafe(16)
    try:
        await asyncio.to_thread(
            docker_service.exec_wp_cli, slug,
            ["wp", "user", "update", slug, f"--user_pass={new_pass}", "--skip-email"]
        )
    except Exception as e:
        _log.error("Echec reset mot de passe WP pour %s : %s", slug, e)
        raise HTTPException(status_code=500, detail="Erreur interne lors de la réinitialisation du mot de passe WordPress") from e
    # Mot de passe non stocké en DB — renvoyé une seule fois dans la réponse
    return {"slug": slug, "new_wp_password": new_pass}


@router.post("/sites/{slug}/reset-smtp-password", summary="Régénérer le mot de passe SMTP ForwardEmail")
async def reset_smtp_password(slug: str = _SLUG_PATH, db: Session = Depends(get_db), _=Depends(require_api_token)):
    from app.services import forwardemail_service
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    if site.status != SiteStatus.ready:
        raise HTTPException(status_code=409, detail="Le site n'est pas en état ready")
    try:
        new_smtp_pass = await asyncio.to_thread(forwardemail_service.generate_smtp_password, slug)
        await asyncio.to_thread(docker_service.update_smtp_env, slug, new_smtp_pass)
    except Exception as e:
        _log.error("Echec reset mot de passe SMTP pour %s : %s", slug, e)
        raise HTTPException(status_code=500, detail="Erreur interne lors de la réinitialisation du mot de passe SMTP") from e
    site.smtp_pass_encrypted = settings.encrypt(new_smtp_pass)
    db.commit()
    return {"slug": slug, "smtp_updated": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site_out(site: Site) -> SiteOut:
    return SiteOut(
        slug=site.slug,
        status=site.status.value if hasattr(site.status, "value") else site.status,
        client_email=site.client_email,
        url=f"https://{site.slug}.{settings.BASE_DOMAIN}",
        container_status=docker_service.get_container_status(site.slug),
    )
