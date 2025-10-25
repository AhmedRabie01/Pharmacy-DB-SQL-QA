from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

# keep absolute imports; --app-dir .. will make the parent visible
from app.routers.query import router as query_router
from app.core.config import settings

app = FastAPI(
    title="PharmacyDB SQL API",
    description="Pattern + LangChain (Ollama) + Agents (Ollama) routes for SQL Q&A.",
    version="1.0.0",
)

# ---- CORS from .env ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- API routes ----
app.include_router(query_router)

# ---- Frontend static (path-safe whether you run from root or from app/) ----
BASE_DIR = Path(__file__).resolve().parent        # .../app
FRONTEND_DIR = BASE_DIR / "frontend"              # .../app/frontend

if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# Redirect root "/" -> "/app/" if frontend exists, otherwise health-ish response
@app.get("/")
def root():
    if FRONTEND_DIR.exists():
        return RedirectResponse(url="/app/")
    return {"ok": True}
