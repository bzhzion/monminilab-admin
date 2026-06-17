from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Migrations SQLite légères : ajoute les colonnes/index manquants sans Alembic."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(
            text("PRAGMA table_info(sites)")
        )}
        if "client_cf_email" not in existing:
            conn.execute(text(
                "ALTER TABLE sites ADD COLUMN client_cf_email VARCHAR(255)"
            ))
        # Index unique sur port (ignoré si déjà présent)
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sites_port ON sites(port)"
        ))
        conn.commit()
