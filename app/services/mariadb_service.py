import re
import secrets
import string

import pymysql

from app.config import settings

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,28}[a-z0-9]$")


def _random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _connect():
    return pymysql.connect(
        host=settings.MARIADB_HOST,
        user=settings.MARIADB_ROOT_USER,
        password=settings.MARIADB_ROOT_PASSWORD,
        autocommit=True,
    )


def create_database(slug: str) -> tuple[str, str, str]:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Slug invalide : {slug!r}")
    db_name = f"wp_{slug}"
    db_user = f"wp_{slug}"
    db_pass = _random_password()

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur.execute(f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_pass}'")
            cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'%'")
            cur.execute("FLUSH PRIVILEGES")
    finally:
        conn.close()

    return db_name, db_user, db_pass


def drop_database(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Slug invalide : {slug!r}")
    db_name = f"wp_{slug}"
    db_user = f"wp_{slug}"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
            cur.execute(f"DROP USER IF EXISTS '{db_user}'@'%'")
            cur.execute("FLUSH PRIVILEGES")
    finally:
        conn.close()
