import base64
import hashlib
import re
import secrets

from cryptography.fernet import Fernet
from passlib.context import CryptContext
from pydantic_settings import BaseSettings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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
                return pwd_context.verify(plain, self.ADMIN_PASSWORD)
            except Exception:
                return False
        return secrets.compare_digest(plain.encode(), self.ADMIN_PASSWORD.encode())

    def _fernet(self) -> Fernet:
        key = base64.urlsafe_b64encode(hashlib.sha256(self.SECRET_KEY.encode()).digest())
        return Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except Exception:
            return value  # fallback pour données legacy en clair

    class Config:
        env_file = ".env"


settings = Settings()
