import urllib
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.core.config import settings

def make_engine() -> Engine:
    """
    Create a SQLAlchemy engine for SQL Server using pyodbc.
    Supports:
      - Windows Trusted Connection (DB_TRUSTED=true)
      - SQL Authentication (DB_TRUSTED=false + DB_USERNAME/DB_PASSWORD)
    """
    parts = [
        f"DRIVER={settings.db_driver}",
        f"SERVER={settings.db_server}",
        f"DATABASE={settings.db_name}",
    ]

    if settings.db_trusted:
        parts.append("Trusted_Connection=yes")
    else:
        if not settings.db_username or not settings.db_password:
            raise ValueError("DB_TRUSTED=false requires DB_USERNAME and DB_PASSWORD.")
        parts.append(f"UID={settings.db_username}")
        parts.append(f"PWD={settings.db_password}")

    odbc_str = ";".join(parts) + ";"
    uri = "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc_str)

    engine = create_engine(uri, pool_pre_ping=True, future=True)
    # quick probe
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

# Singleton
engine: Engine = make_engine()
