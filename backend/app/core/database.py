import logging
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MIN_POSTGRES_MAJOR_VERSION = 15

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine | None:
    """Lazily initialize the SQLAlchemy engine if DATABASE_URL is configured."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    settings = get_settings()
    if not settings.database_url:
        return None

    _engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI route dependencies."""
    get_engine()
    if _session_factory is None:
        raise RuntimeError("Database engine is not configured.")
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> tuple[bool, int | None, str]:
    """
    Verify PostgreSQL connectivity and minimum version (>= 15).
    Returns (is_healthy, major_version, sanitized_status_code).
    Never exposes raw driver errors or credentials to callers.
    """
    engine = get_engine()
    if engine is None:
        return False, None, "database_not_configured"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            version_num_raw = conn.execute(text("SHOW server_version_num")).scalar_one()
            version_num = int(version_num_raw)
            major_version = version_num // 10000
            if major_version < MIN_POSTGRES_MAJOR_VERSION:
                logger.warning("PostgreSQL version %s is below minimum %s", major_version, MIN_POSTGRES_MAJOR_VERSION)
                return False, major_version, "unsupported_database_version"
            return True, major_version, "connected"
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        return False, None, "database_unavailable"
    except Exception:
        logger.exception("Unexpected error during database health check")
        return False, None, "database_unavailable"
