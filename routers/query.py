import time
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.schemas.requests import QuestionRequest, SQLRunRequest
from app.schemas.responses import QueryResponse, PresetsList, PresetRunResponse
from app.utils.sql_safety import enforce_select_only
from app.services.pattern import PatternSQLGenerator
from app.services.langchain_sql import generate_and_execute
from app.services.agents import agents
from app.presets import IMPORTANT_QUERIES
from app.services.ollama_client import generate_with_metrics


router = APIRouter(prefix="/api", tags=["query"])

@router.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "db": settings.db_name, "model": settings.ollama_model}

@router.get("/llm/warmup")
def llm_warmup():
    """
    Loads the model into memory quickly (1 token) and keeps it alive.
    """
    out = generate_with_metrics("ping", num_predict=1, timeout=settings.ollama_timeout)
    return {
        "status": "warmed",
        "model": out.get("model"),
        "prompt_tokens": out.get("prompt_eval_count", 0),
        "eval_tokens": out.get("eval_count", 0),
        "llm_duration_ms": out.get("total_duration_ms", 0),
    }

@router.post("/pattern", response_model=QueryResponse)
def pattern_route(req: QuestionRequest):
    t0 = time.perf_counter()
    sql = PatternSQLGenerator.generate(req.question)
    if not sql:
        raise HTTPException(400, "لا يوجد نمط مناسب للسؤال المدخل.")
    safe = enforce_select_only(sql)
    df = pd.read_sql_query(text(safe), engine)
    if len(df) > settings.preview_limit:
        df = df.head(settings.preview_limit)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return QueryResponse(
        route="pattern",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"عدد الصفوف المعروضة: {len(df)} | الأعمدة: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
        model=None,
        llm_prompt_tokens=0,
        llm_eval_tokens=0,
        llm_total_tokens=0,
        llm_duration_ms=0,
        total_ms=total_ms,
    )

@router.post("/langchain", response_model=QueryResponse)
def langchain_route(req: QuestionRequest):
    try:
        result = generate_and_execute(req.question, settings.preview_limit)
        return QueryResponse(route="langchain", **result)
    except Exception as e:
        raise HTTPException(400, f"خطأ في توليد/تنفيذ SQL عبر LLM: {e}")

@router.post("/agents", response_model=QueryResponse)
def agents_route(req: QuestionRequest):
    try:
        result = agents.run(req.question, settings.preview_limit)
        return QueryResponse(route="agents", **result)
    except Exception as e:
        raise HTTPException(400, f"خطأ في مسار الوكلاء (Agents): {e}")

@router.post("/run-sql", response_model=QueryResponse)
def run_sql(req: SQLRunRequest):
    t0 = time.perf_counter()
    safe = enforce_select_only(req.sql)
    df = pd.read_sql_query(text(safe), engine)
    if len(df) > settings.preview_limit:
        df = df.head(settings.preview_limit)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return QueryResponse(
        route="manual-sql",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"عدد الصفوف المعروضة: {len(df)} | الأعمدة: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
        model=None,
        llm_prompt_tokens=0,
        llm_eval_tokens=0,
        llm_total_tokens=0,
        llm_duration_ms=0,
        total_ms=total_ms,
    )

@router.get("/presets", response_model=PresetsList)
def list_presets():
    return PresetsList(presets={k: v.strip() for k, v in IMPORTANT_QUERIES.items()})

@router.post("/presets/run", response_model=PresetRunResponse)
def run_preset(name: str = Query(..., description="Preset name (Arabic label).")):
    t0 = time.perf_counter()
    sql = IMPORTANT_QUERIES.get(name)
    if not sql:
        raise HTTPException(404, "Preset not found.")
    safe = enforce_select_only(sql)
    df = pd.read_sql_query(text(safe), engine)
    if len(df) > settings.preview_limit:
        df = df.head(settings.preview_limit)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return PresetRunResponse(
        preset_name=name,
        route="preset",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"عدد الصفوف المعروضة: {len(df)} | الأعمدة: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
        model=None,
        llm_prompt_tokens=0,
        llm_eval_tokens=0,
        llm_total_tokens=0,
        llm_duration_ms=0,
        total_ms=total_ms,
    )
