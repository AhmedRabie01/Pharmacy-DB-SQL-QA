from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from app.core.config import settings
from app.routers.query import router as query_router

app = FastAPI(title="PharmacyDB LLM API", version="1.0.0")

origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router)

_frontend = Path(__file__).parent / "frontend"
if _frontend.exists():
    app.mount("/app", StaticFiles(directory=str(_frontend), html=True), name="frontend")

@app.get("/")
def root():
    return {"name": "PharmacyDB LLM API", "db": settings.db_name, "model": settings.ollama_model, "status": "ok"}
