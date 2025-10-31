# app/routers/query.py
import re
import time
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_engine
from app.schemas.requests import QuestionRequest, SQLRunRequest
from app.schemas.responses import QueryResponse, PresetsList, PresetRunResponse
from app.utils.sql_safety import enforce_select_only
from app.services.pattern import PatternSQLGenerator
from app.services.langchain_sql import generate_and_execute
from app.services.agents import get_agents
from app.presets import IMPORTANT_QUERIES
from app.services.ollama_client import generate_with_metrics

router = APIRouter(prefix="/api", tags=["query"])


def _extract_requested_top(sql: str) -> int | None:
    """
    Try to detect a TOP N in the T-SQL statement.
    Returns N or None.
    """
    m = re.search(r"\bTOP\s+(\d+)\b", sql, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _trim_df_by_sql(df: pd.DataFrame, sql: str) -> pd.DataFrame:
    """
    If user explicitly asked for TOP N, keep N rows (but never negative).
    Otherwise use settings.preview_limit.
    """
    asked = _extract_requested_top(sql)
    if asked is not None:
        # allow up to the user's asked number, but do not explode to huge numbers
        hard_cap = getattr(settings, "max_return_rows", 500)
        limit = min(asked, hard_cap)
        if len(df) > limit:
            return df.head(limit)
        return df
    # default behavior
    if len(df) > settings.preview_limit:
        return df.head(settings.preview_limit)
    return df


@router.get("/health")
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        print(f"[health] DB error: {e}")
        db_ok = False

    out = generate_with_metrics("ping", num_predict=1, timeout_seconds=4.0)
    llm_ok = not out.get("error")

    return {
        "status": "ok" if db_ok else "db-failed",
        "db": settings.db_name,
        "llm_ok": llm_ok,
        "llm_error": out.get("error"),
    }


@router.get("/llm/warmup")
def llm_warmup():
    out = generate_with_metrics("ping", num_predict=1, timeout_seconds=6.0)
    if out.get("error"):
        raise HTTPException(500, f"LLM warmup failed: {out['error']}")
    return {
        "status": "warmed",
        "model": out.get("model"),
        "prompt_tokens": out.get("prompt_eval_count", 0),
        "eval_tokens": out.get("eval_count", 0),
        "llm_duration_ms": out.get("total_duration_ms", 0),
    }


@router.post("/pattern", response_model=QueryResponse)
def pattern_route(req: QuestionRequest):
    """
    1) Try pattern-based SQL.
    2) If no pattern, fall back to langchain route.
    """
    t0 = time.perf_counter()
    sql = PatternSQLGenerator.generate(req.question)

    # no pattern -> fallback to LLM route
    if not sql:
        print("[pattern] no pattern matched, falling back to langchain...")
        result = generate_and_execute(req.question, settings.preview_limit)
        return QueryResponse(route="pattern→langchain", **result)

    try:
        safe = enforce_select_only(sql)
        df = pd.read_sql_query(text(safe), get_engine())
    except Exception as e:
        print(f"[pattern] error, falling back to langchain: {e}")
        result = generate_and_execute(req.question, settings.preview_limit)
        return QueryResponse(route="pattern→langchain", **result)

    df = _trim_df_by_sql(df, safe)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return QueryResponse(
        route="pattern",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
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
        print(f"[langchain] error: {e}")
        raise HTTPException(500, f"LLM SQL generation/execution error: {e}")


@router.post("/agents", response_model=QueryResponse)
def agents_route(req: QuestionRequest):
    try:
        agent = get_agents()
        result = agent.run(req.question, settings.preview_limit)
        return QueryResponse(route="agents", **result)
    except Exception as e:
        print(f"[agents] route error: {e}")
        raise HTTPException(500, f"Agents route error: {e}")


@router.post("/run-sql", response_model=QueryResponse)
def run_sql(req: SQLRunRequest):
    t0 = time.perf_counter()
    try:
        safe = enforce_select_only(req.sql)
        df = pd.read_sql_query(text(safe), get_engine())
    except Exception as e:
        print(f"[run-sql] error: {e}")
        raise HTTPException(500, f"Run-SQL error: {e}")

    df = _trim_df_by_sql(df, safe)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return QueryResponse(
        route="manual-sql",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
        model=None,
        llm_prompt_tokens=0,
        llm_eval_tokens=0,
        llm_total_tokens=0,
        llm_duration_ms=0,
        total_ms=total_ms,
    )


@router.get("/presets", response_model=PresetsList)
def list_presets():
    cleaned = {}
    for k, v in IMPORTANT_QUERIES.items():
        cleaned[k] = v.strip() if isinstance(v, str) else str(v)
    return PresetsList(presets=cleaned)


@router.post("/presets/run", response_model=PresetRunResponse)
def run_preset(name: str = Query(..., description="Preset name (Arabic label).")):
    t0 = time.perf_counter()
    sql = IMPORTANT_QUERIES.get(name)
    if not sql:
        raise HTTPException(404, "Preset not found.")
    try:
        safe = enforce_select_only(sql)
        df = pd.read_sql_query(text(safe), get_engine())
    except Exception as e:
        print(f"[presets/run] error: {e}")
        raise HTTPException(500, f"Preset run error: {e}")

    df = _trim_df_by_sql(df, safe)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return PresetRunResponse(
        preset_name=name,
        route="preset",
        sql=safe,
        columns=list(df.columns),
        rows=df.to_dict(orient="records"),
        summary_ar=f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
        model=None,
        llm_prompt_tokens=0,
        llm_eval_tokens=0,
        llm_total_tokens=0,
        llm_duration_ms=0,
        total_ms=total_ms,
    )
