# app/db/session.py
from functools import lru_cache
import urllib.parse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings


def _build_pyodbc_url_from_env() -> str:
    """
    Build a SQL Server pyodbc URL from environment-style settings.
    This lets the app work inside Docker without a DSN.
    """
    parts = [f"DRIVER={settings.db_driver}"]

    # server + optional port
    if settings.db_port:
        parts.append(f"SERVER={settings.db_server},{settings.db_port}")
    else:
        parts.append(f"SERVER={settings.db_server}")

    parts.append(f"DATABASE={settings.db_name}")
    parts.append(f"Encrypt={settings.db_encrypt}")
    parts.append(f"TrustServerCertificate={settings.db_trust_server_cert}")
    parts.append(f"Connection Timeout={settings.db_connect_timeout}")

    if settings.db_trusted:
        # Windows Integrated
        parts.append("Trusted_Connection=yes")
    else:
        # Username / password
        if not settings.db_username or not settings.db_password:
            raise ValueError("DB_TRUSTED=false requires DB_USERNAME and DB_PASSWORD.")
        parts.append(f"UID={settings.db_username}")
        parts.append(f"PWD={settings.db_password}")

    odbc_str = ";".join(parts)
    return "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc_str)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    Return the single SQLAlchemy engine used across the app.
    All code must call get_engine() and NOT import a global `engine`.
    """
    if settings.database_url:
        uri = settings.database_url.strip().strip('"').strip("'")
    else:
        uri = _build_pyodbc_url_from_env()

    engine = create_engine(
        uri,
        pool_pre_ping=True,
        pool_recycle=180,
        future=True,
    )
    return engine


def verify_connection(raise_on_error: bool = False) -> bool:
    """
    Optional health check. You can call this on startup.
    """
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[DB] verify_connection failed: {e}")
        if raise_on_error:
            raise
        return False
