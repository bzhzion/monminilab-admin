from datetime import datetime

import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String

from app.database import Base


class SiteStatus(str, enum.Enum):
    creating = "creating"
    ready = "ready"
    error = "error"


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(30), unique=True, index=True, nullable=False)
    port = Column(Integer, nullable=False)
    client_email = Column(String(255), nullable=False)
    smtp_pass_encrypted = Column(String(500), nullable=True)
    wp_admin_password = Column(String(255), nullable=True)  # colonne conservée pour compat DB, ne plus écrire
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(SiteStatus), default=SiteStatus.creating, nullable=False)
