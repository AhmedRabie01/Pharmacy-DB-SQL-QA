from __future__ import annotations
from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import json, re

def _parse_duration_to_seconds(v, default_sec: int) -> int:
    """
    Accepts:
      - int/float seconds (e.g., 30, 600)
      - strings like "30", "45s", "10m", "1h"
    Returns total seconds (int). Falls back to default_sec if value is empty/invalid.
    """
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
    if unit == "h":
        return num * 3600
    return default_sec

class Settings(BaseSettings):
    # ---------------- Database ----------------
    db_server: str = Field(".", alias="DB_SERVER")
    db_name: str = Field("PharmacyDB", alias="DB_NAME")
    db_driver: str = Field("{ODBC Driver 17 for SQL Server}", alias="DB_DRIVER")
    db_trusted: bool = Field(True, alias="DB_TRUSTED")
    db_username: Optional[str] = Field(None, alias="DB_USERNAME")
    db_password: Optional[str] = Field(None, alias="DB_PASSWORD")

    # ---------------- LLM (Ollama) ----------------
    ollama_model: str = Field("qwen2.5-coder:latest", alias="OLLAMA_MODEL")
    ollama_base_url: Optional[str] = Field(None, alias="OLLAMA_BASE_URL")  # None -> default http://127.0.0.1:11434
    ollama_temperature: float = Field(0.0, alias="OLLAMA_TEMPERATURE")
    ollama_num_predict: int = Field(128, alias="OLLAMA_NUM_PREDICT")

    # Accept "30", "45s", "10m", "1h" in .env and store as seconds (int)
    ollama_timeout: int = Field(30, alias="OLLAMA_TIMEOUT")
    ollama_keep_alive: int = Field(900, alias="OLLAMA_KEEP_ALIVE")

    # ---------------- API & Security ----------------
    cors_origins: str = Field("*", alias="CORS_ORIGINS")  # CSV or JSON list
    preview_limit: int = Field(200, alias="PREVIEW_LIMIT")

    class Config:
        env_file = ".env"
        case_sensitive = False

    # ---- Parse durations from env into seconds ----
    @field_validator("ollama_timeout", mode="before")
    @classmethod
    def _v_timeout(cls, v):
        return _parse_duration_to_seconds(v, 30)

    @field_validator("ollama_keep_alive", mode="before")
    @classmethod
    def _v_keepalive(cls, v):
        return _parse_duration_to_seconds(v, 900)

    # ---- CORS helper (CSV or JSON list) ----
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
