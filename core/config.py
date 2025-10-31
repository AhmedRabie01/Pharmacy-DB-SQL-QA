# app/core/config.py
from __future__ import annotations

from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import json
import re


def _parse_duration_to_seconds(v, default_sec: int) -> int:
    if v is None:
        return default_sec
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower()
    if not s:
        return default_sec
    if s.isdigit():
        return int(s)
    m = re.fullmatch(r"(\d+)\s*([smh])", s)
    if not m:
        m2 = re.search(r"\d+", s)
        return int(m2.group()) if m2 else default_sec
    num, unit = int(m.group(1)), m.group(2)
    if unit == "s":
        return num
    if unit == "m":
        return num * 60
    return num * 3600


class Settings(BaseSettings):
    # optional raw SQLAlchemy URL, if set we use it as-is
    database_url: Optional[str] = Field(None, alias="DATABASE_URL")

    # Database pieces (used to build pyodbc URL if database_url is not set)
    db_server: str = Field(".", alias="DB_SERVER")
    db_port: int = Field(1433, alias="DB_PORT")
    db_name: str = Field("PharmacyDB", alias="DB_NAME")
    db_driver: str = Field("{ODBC Driver 18 for SQL Server}", alias="DB_DRIVER")
    db_trusted: bool = Field(True, alias="DB_TRUSTED")
    db_username: Optional[str] = Field(None, alias="DB_USERNAME")
    db_password: Optional[str] = Field(None, alias="DB_PASSWORD")
    db_encrypt: str = Field("yes", alias="DB_ENCRYPT")
    db_trust_server_cert: str = Field("yes", alias="DB_TRUST_SERVER_CERT")
    db_connect_timeout: int = Field(15, alias="DB_CONNECT_TIMEOUT")
    db_skip_startup_check: bool = Field(True, alias="DB_SKIP_STARTUP_CHECK")

    # LLM / Ollama
    ollama_model: str = Field("qwen2.5-coder:latest", alias="OLLAMA_MODEL")
    ollama_base_url: Optional[str] = Field(None, alias="OLLAMA_BASE_URL")
    ollama_temperature: float = Field(0.0, alias="OLLAMA_TEMPERATURE")
    ollama_num_predict: int = Field(128, alias="OLLAMA_NUM_PREDICT")
    ollama_timeout: int = Field(30, alias="OLLAMA_TIMEOUT")
    ollama_keep_alive: int = Field(900, alias="OLLAMA_KEEP_ALIVE")

    # API
    cors_origins: str = Field("*", alias="CORS_ORIGINS")
    preview_limit: int = Field(200, alias="PREVIEW_LIMIT")

    class Config:
        env_file = ".env"
        case_sensitive = False

    @field_validator("ollama_timeout", mode="before")
    @classmethod
    def _v_timeout(cls, v):
        return _parse_duration_to_seconds(v, 30)

    @field_validator("ollama_keep_alive", mode="before")
    @classmethod
    def _v_keepalive(cls, v):
        return _parse_duration_to_seconds(v, 900)

    @property
    def cors_origins_list(self) -> List[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        if raw.startswith("[") and raw.endswith("]"):
            try:
                arr = json.loads(raw)
                return [s.strip() for s in arr if isinstance(s, str)]
            except Exception:
                pass
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
