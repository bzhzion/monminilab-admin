import logging
import sys

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.auth import AdminRedirect
from app.config import _BCRYPT_RE, settings
from app.database import init_db
from app.limiter import limiter
from app.routers import admin, api, user

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
_log = logging.getLogger("monminilab")

app = FastAPI(title="MonMiniLab Admin", docs_url="/api/docs", redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, max_age=86400, same_site="strict", https_only=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(admin.router)
app.include_router(user.router)
app.include_router(api.router)


@app.exception_handler(AdminRedirect)
async def admin_redirect_handler(request: Request, exc: AdminRedirect):
    return RedirectResponse("/admin/login", status_code=303)


@app.on_event("startup")
async def on_startup():
    init_db()
    _DEFAULT_KEY = "change-this-to-a-long-random-string"
    if settings.SECRET_KEY == _DEFAULT_KEY:
        _log.error(
            "SECRET_KEY non modifie (valeur par defaut) - refus de demarrer. "
            "Generez-en un avec : python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
        sys.exit(1)
    if len(settings.SECRET_KEY) < 32:
        _log.warning(
            "SECRET_KEY court (%d chars) - recommande : 32+ chars aleatoires. "
            "Generez-en un avec : python3 -c \"import secrets; print(secrets.token_hex(32))\"",
            len(settings.SECRET_KEY),
        )
    if not _BCRYPT_RE.match(settings.ADMIN_PASSWORD):
        _log.warning(
            "ADMIN_PASSWORD n'est pas un hash bcrypt - le mot de passe est stocke en clair. "
            "Generez un hash avec : "
            "python3 -c \"from passlib.context import CryptContext; print(CryptContext(['bcrypt']).hash('votre-mdp'))\""
        )
