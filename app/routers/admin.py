import asyncio
import logging
import secrets
from datetime import timedelta

_log = logging.getLogger("monminilab.provision")

from email_validator import EmailNotValidError, validate_email as _validate_email

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import create_access_token, require_admin
from app.config import settings
from app.database import SessionLocal, get_db
from app.models import Site, SiteStatus
from app.services import cloudflare_service, docker_service, forwardemail_service, mail_service, mariadb_service
from app.validators import RESERVED_SLUGS, SLUG_RE

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_SLUG_PATH = Path(..., pattern=SLUG_RE.pattern)
_RESERVED_SLUGS = RESERVED_SLUGS

# État des provisionnements en cours : slug → dict
JOBS: dict[str, dict] = {}


def _job_step(job: dict, n: int, label: str | None = None, status: str = "running") -> None:
    if label:
        job["labels"][n] = label
    job["steps"][n] = status


def _job_log(job: dict, msg: str, level: str = "info") -> None:
    import datetime
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    job["log"].append({"ts": ts, "level": level, "msg": msg})
    if level == "error":
        _log.error(msg)
    else:
        _log.info(msg)


async def _run_provisioning(slug: str, client_email: str, port: int) -> None:
    """Tâche de fond : exécute les 8 étapes et met à jour JOBS[slug]."""
    job = JOBS[slug]
    alias_email = f"{slug}@{settings.BASE_DOMAIN}"

    created_db = created_alias = created_container = created_tunnel = False
    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.slug == slug).first()
        _job_log(job, f"Démarrage provisionnement pour {slug} (port {port})")

        # Étape 1 — MariaDB
        _job_step(job, 1, "Base de données MariaDB")
        _job_log(job, f"Création BDD MariaDB : {slug}")
        db_name, db_user, db_pass = await asyncio.to_thread(mariadb_service.create_database, slug)
        created_db = True
        _job_step(job, 1, status="done")
        _job_log(job, f"BDD créée : {db_name} / user {db_user}")

        # Étape 2 — Alias email
        _job_step(job, 2, f"Alias email {alias_email}")
        _job_log(job, f"Création alias ForwardEmail : {alias_email} → {client_email}")
        await asyncio.to_thread(forwardemail_service.create_alias, slug, client_email)
        created_alias = True
        _job_step(job, 2, status="done")
        _job_log(job, "Alias email créé")

        # Étape 3 — Mot de passe SMTP
        _job_step(job, 3, "Mot de passe SMTP ForwardEmail")
        _job_log(job, "Génération mot de passe SMTP")
        smtp_pass = await asyncio.to_thread(forwardemail_service.generate_smtp_password, slug)
        _job_step(job, 3, status="done")
        _job_log(job, "Mot de passe SMTP généré")

        # Étape 4 — Création container
        wp_admin_pass = secrets.token_urlsafe(16)
        _job_step(job, 4, "Création container WordPress")
        _job_log(job, f"Lancement container Docker wp-{slug} sur port {port}")
        await asyncio.to_thread(
            lambda: docker_service.create_wp_container(
                slug=slug, port=port, db_name=db_name,
                db_user=db_user, db_pass=db_pass,
                mariadb_host=settings.MARIADB_HOST,
                smtp_user=alias_email,
                smtp_pass=smtp_pass,
            )
        )
        created_container = True
        _job_step(job, 4, status="done")
        _job_log(job, "Container WordPress démarré")

        # Étape 5 — Attente démarrage WordPress
        _job_step(job, 5, "Démarrage WordPress…")
        _job_log(job, "Attente que WordPress soit prêt (HTTP 2xx/3xx/4xx)…")
        deadline = asyncio.get_event_loop().time() + 300
        attempts = 0
        while True:
            ready = await asyncio.to_thread(docker_service.check_wordpress_ready, slug)
            attempts += 1
            if ready:
                break
            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError("WordPress n'a pas démarré dans les 5 minutes")
            if attempts % 10 == 0:
                _job_log(job, f"Toujours en attente… ({attempts * 3}s écoulées)")
            await asyncio.sleep(3)
        _job_step(job, 5, status="done")
        _job_log(job, f"WordPress prêt après {attempts * 3}s")

        # Étape 6 — Installation WordPress
        _job_step(job, 6, "Installation WordPress")
        _job_log(job, f"wp core install — url https://{slug}.{settings.BASE_DOMAIN}, user {slug}")
        await asyncio.to_thread(docker_service.install_wordpress, slug, wp_admin_pass, alias_email)
        _job_step(job, 6, status="done")
        _job_log(job, "WordPress installé")

        # Étape 7 — Cloudflare
        _job_step(job, 7, "Tunnel Cloudflare + DNS")
        _job_log(job, f"Ajout ingress tunnel Cloudflare pour {slug} → port {port}")
        await asyncio.to_thread(cloudflare_service.add_tunnel_ingress, slug, port)
        _job_log(job, f"Ajout enregistrement DNS {slug}.{settings.BASE_DOMAIN}")
        await asyncio.to_thread(cloudflare_service.add_dns_record, slug)
        created_tunnel = True
        _job_step(job, 7, status="done")
        _job_log(job, "Tunnel et DNS configurés")

        # Étape 8 — Email de bienvenue
        _job_step(job, 8, "Envoi email de bienvenue")
        _job_log(job, f"Envoi email de bienvenue à {client_email}")
        await asyncio.to_thread(
            mail_service.send_welcome_email,
            slug, smtp_pass, wp_admin_pass, client_email,
        )
        _job_step(job, 8, status="done")
        _job_log(job, "Email de bienvenue envoyé")

        site.smtp_pass_encrypted = settings.encrypt(smtp_pass)
        site.status = SiteStatus.ready
        db.commit()

        job["done"] = True
        job["url"] = f"https://{slug}.{settings.BASE_DOMAIN}"
        _job_log(job, f"Provisionnement terminé — {job['url']}")

    except Exception as e:
        msg = str(e)
        job["error"] = msg
        _job_log(job, f"ERREUR : {msg}", level="error")
        if site := db.query(Site).filter(Site.slug == slug).first():
            site.status = SiteStatus.error
            db.commit()
        if created_tunnel:
            try:
                _job_log(job, "Rollback : suppression tunnel/DNS Cloudflare")
                cloudflare_service.remove_tunnel_ingress(slug)
                cloudflare_service.remove_dns_record(slug)
            except Exception:
                pass
        if created_container:
            _job_log(job, "Rollback : suppression container WordPress")
            docker_service.remove_wp_container(slug)
        if created_alias:
            _job_log(job, "Rollback : suppression alias email")
            forwardemail_service.delete_alias(slug)
        if created_db:
            _job_log(job, "Rollback : suppression BDD MariaDB")
            mariadb_service.drop_database(slug)
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/admin")


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"role": "admin", "error": None})


@router.post("/admin/login")
async def admin_login(request: Request, password: str = Form(..., max_length=128)):
    if not settings.verify_admin_password(password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"role": "admin", "error": "Mot de passe incorrect"},
            status_code=401,
        )
    token = create_access_token({"sub": "admin"}, timedelta(hours=24))
    request.session["admin_token"] = token
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    sites = db.query(Site).order_by(Site.created_at.desc()).all()
    return templates.TemplateResponse(request, "admin/dashboard.html", {"sites": sites, "domain": settings.BASE_DOMAIN})


@router.get("/admin/create", response_class=HTMLResponse)
async def admin_create_page(request: Request, _: bool = Depends(require_admin)):
    return templates.TemplateResponse(request, "admin/create.html", {})


@router.post("/admin/provision")
async def provision_start(
    request: Request,
    slug: str = Form(...),
    client_email: str = Form(...),
    _: bool = Depends(require_admin),
):
    slug = slug.strip().lower()

    if not SLUG_RE.match(slug):
        return JSONResponse({"error": "Slug invalide (3-30 chars alphanumériques/tirets)"}, status_code=400)

    if slug in _RESERVED_SLUGS:
        return JSONResponse({"error": f"Le slug '{slug}' est réservé et ne peut pas être utilisé"}, status_code=400)

    try:
        email_info = _validate_email(client_email.strip(), check_deliverability=False)
        client_email = email_info.normalized
    except EmailNotValidError as exc:
        return JSONResponse({"error": f"Email invalide : {exc}"}, status_code=400)

    db = SessionLocal()
    try:
        if db.query(Site).filter(Site.slug == slug).first():
            return JSONResponse({"error": f"Le slug '{slug}' est déjà utilisé"}, status_code=409)

        last_port = db.query(Site.port).order_by(Site.port.desc()).first()
        port = (last_port[0] + 1) if last_port else settings.PORT_START

        site = Site(slug=slug, port=port, client_email=client_email, status=SiteStatus.creating)
        db.add(site)
        db.commit()
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

    asyncio.create_task(_run_provisioning(slug, client_email, port))
    return JSONResponse({"slug": slug})


@router.get("/admin/provision-status/{slug}")
async def provision_status(slug: str = _SLUG_PATH, _: bool = Depends(require_admin)):
    if slug not in JOBS:
        # Tâche non trouvée en mémoire — on regarde la DB (app redémarrée ?)
        db = SessionLocal()
        try:
            site = db.query(Site).filter(Site.slug == slug).first()
            if not site:
                raise HTTPException(status_code=404, detail="Job introuvable")
            if site.status == SiteStatus.ready:
                return JSONResponse({
                    "done": True,
                    "error": None,
                    "url": f"https://{slug}.{settings.BASE_DOMAIN}",
                    "steps": {n: "done" for n in range(1, 9)},
                    "labels": {},
                })
            return JSONResponse({"done": False, "error": "Job perdu (app redémarrée)", "steps": {}, "labels": {}})
        finally:
            db.close()

    return JSONResponse(JOBS[slug])


@router.post("/admin/sites/{slug}/delete")
async def admin_delete_site(request: Request, slug: str = _SLUG_PATH, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    site = db.query(Site).filter(Site.slug == slug).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site introuvable")
    await teardown_site(slug, db)
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/setup-portail")
async def setup_portail(_: bool = Depends(require_admin)):
    try:
        cloudflare_service.add_tunnel_ingress("portail", 8000)
        cloudflare_service.add_dns_record("portail")
        return JSONResponse({"ok": True, "message": "portail.monminilab.fr ajouté au tunnel et au DNS."})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=500)


@router.get("/admin/sites/{slug}/logs", response_class=HTMLResponse)
async def site_logs(request: Request, slug: str = _SLUG_PATH, _: bool = Depends(require_admin)):
    logs = await asyncio.to_thread(docker_service.get_container_logs, slug)
    return templates.TemplateResponse(request, "admin/logs.html", {
        "slug": slug,
        "logs": logs,
        "title": f"Logs — {slug}.{settings.BASE_DOMAIN}",
        "back_url": "/admin",
        "back_label": "Dashboard",
        "subtitle": f"Container Docker wp-{slug} (300 dernières lignes)",
    })


@router.get("/admin/logs", response_class=HTMLResponse)
async def app_logs(request: Request, _: bool = Depends(require_admin)):
    logs = await asyncio.to_thread(docker_service.get_app_logs)
    return templates.TemplateResponse(request, "admin/logs.html", {
        "slug": None,
        "logs": logs,
        "title": "Logs — Application",
        "back_url": "/admin",
        "back_label": "Dashboard",
        "subtitle": "Container monminilab-admin (500 dernières lignes)",
    })


async def teardown_site(slug: str, db: Session) -> None:
    cloudflare_service.remove_tunnel_ingress(slug)
    cloudflare_service.remove_dns_record(slug)
    forwardemail_service.delete_alias(slug)
    docker_service.remove_wp_container(slug)
    mariadb_service.drop_database(slug)

    site = db.query(Site).filter(Site.slug == slug).first()
    if site:
        db.delete(site)
        db.commit()
