import base64
import re
import secrets

import bcrypt as _bcrypt

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic_settings import BaseSettings

_BCRYPT_RE = re.compile(r"^\$2[aby]\$")


class Settings(BaseSettings):
    ADMIN_PASSWORD: str
    SECRET_KEY: str
    DB_PATH: str = "/data/app.db"

    MARIADB_HOST: str = "wordpress-db"
    MARIADB_ROOT_PASSWORD: str
    MARIADB_ROOT_USER: str = "root"

    CF_TOKEN: str
    CF_GLOBAL_API_KEY: str
    CF_ACCOUNT_EMAIL: str
    CF_ACCOUNT_ID: str
    CF_ZONE_ID: str
    CF_TUNNEL_ID: str

    FE_API_KEY: str

    CF_TEAM_DOMAIN: str = "gochu"
    CF_ACCESS_AUD: str = "845745b9-8e8a-4df5-adc2-52258cac5454"

    WP_IMAGE: str = "ghcr.io/painteau/wordpress"
    BASE_DOMAIN: str = "monminilab.fr"
    PORT_START: int = 8100
    DOCKER_NETWORK: str = "wp-network"
    SITES_DATA_DIR: str = "/home/wordpress"

    def verify_admin_password(self, plain: str) -> bool:
        if _BCRYPT_RE.match(self.ADMIN_PASSWORD):
            try:
                return _bcrypt.checkpw(plain.encode(), self.ADMIN_PASSWORD.encode())
            except Exception:
                return False
        return secrets.compare_digest(plain.encode(), self.ADMIN_PASSWORD.encode())

    def _derive_key(self, info: bytes) -> bytes:
        """Dérive une clé de 32 bytes depuis SECRET_KEY pour un usage donné via HKDF."""
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=info,
        ).derive(self.SECRET_KEY.encode())

    @property
    def fernet_key(self) -> bytes:
        """Clé Fernet (chiffrement du mot de passe SMTP)."""
        return base64.urlsafe_b64encode(self._derive_key(b"fernet"))

    @property
    def jwt_secret(self) -> bytes:
        """Clé pour les JWT de l'API admin."""
        return self._derive_key(b"jwt")

    @property
    def session_secret(self) -> str:
        """Clé pour SessionMiddleware (string hex de 32 bytes)."""
        return self._derive_key(b"session").hex()

    def _fernet(self) -> Fernet:
        return Fernet(self.fernet_key)

    def encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except Exception as exc:
            raise ValueError("Impossible de déchiffrer la valeur") from exc

    class Config:
        env_file = ".env"


settings = Settings()
