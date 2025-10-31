# app/services/langchain_sql.py
from __future__ import annotations

import re
import time
import difflib
import pandas as pd
from typing import Dict, Any, Set, Tuple
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_engine
from app.utils.sql_safety import enforce_select_only
from app.services.ollama_client import generate_with_metrics

# optional original helper
try:
    from langchain_helper import get_few_shot_db_chain
except Exception:
    get_few_shot_db_chain = None  # type: ignore

_SQL_END = re.compile(r";\s*$")
_RX_SELECT = re.compile(r"^\s*(select|with|;with)\b", re.IGNORECASE | re.DOTALL)

# in-memory schema cache
_SCHEMA_CACHE: Dict[str, Set[str]] = {}


def _load_schema() -> Dict[str, Set[str]]:
    """
    Load columns from INFORMATION_SCHEMA for the 3 tables we care about.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE:
        return _SCHEMA_CACHE
    q = """
    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN ('products','selling','buying');
    """
    with get_engine().connect() as conn:
        rows = conn.execute(text(q)).fetchall()
    tables: Dict[str, Set[str]] = {"products": set(), "selling": set(), "buying": set()}
    for sch, tn, col in rows:
        tables[tn.lower()].add(col)
    _SCHEMA_CACHE = tables
    return tables


def _allowed_text() -> str:
    t = _load_schema()
    return (
        "Tables and columns (use ONLY these exact names):\n"
        f"- products: {', '.join(sorted(t['products']))}\n"
        f"- selling : {', '.join(sorted(t['selling']))}\n"
        f"- buying  : {', '.join(sorted(t['buying']))}\n"
    )


# --- same sanitizers as agents ---
_ALIAS_TABLE = {"p": "products", "s": "selling", "b": "buying"}
_BOUNDARY = r"(?=(?:AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|JOIN|UNION|;|$))"

_COMMON_SYNONYMS = {
    r"\b([psb])\.\[?QuantitySelling\]?\b": r"\1.QuantitySold",
    r"\b([psb])\.\[?BuyingPrice\]?\b": r"\1.CostBuying",
    r"\b([psb])\.\[?ManufacturerPrice\]?\b": r"\1.ManufacturerCost",
    r"\b([psb])\.\[?ProductPrice\]?\b": r"\1.ProductSellingPrice",
}
_COMMON_TOKENS = {
    r"\bQuantitySelling\b": "QuantitySold",
    r"\bBuyingPrice\b": "CostBuying",
    r"\bManufacturerPrice\b": "ManufacturerCost",
    r"\bProductPrice\b": "ProductSellingPrice",
    r"\bAverageSelingPrice\b": "AverageSellingPrice",
}


def _basic_cleanup(sql: str) -> str:
    s = (sql or "").strip()
    s = s.replace("`", "'")
    s = re.sub(r"'\s*(AND|OR)\b", r"' \1", s, flags=re.IGNORECASE)
    s = re.sub(r"GETDATE\(\s*-\s*(\d+)\s*\)", r"DATEADD(day, -\1, GETDATE())", s, flags=re.IGNORECASE)
    return s


def _normalize_tables(sql: str) -> str:
    s = sql
    s = re.sub(r"\bFROM\s+\[?Products\]?\b", "FROM [dbo].[products]", s, flags=re.IGNORECASE)
    s = re.sub(r"\bJOIN\s+\[?Products\]?\b", "JOIN [dbo].[products]", s, flags=re.IGNORECASE)
    s = re.sub(r"\bFROM\s+\[?Selling\]?\b", "FROM [dbo].[selling]", s, flags=re.IGNORECASE)
    s = re.sub(r"\bJOIN\s+\[?Selling\]?\b", "JOIN [dbo].[selling]", s, flags=re.IGNORECASE)
    s = re.sub(r"\bFROM\s+\[?Buying\]?\b", "FROM [dbo].[buying]", s, flags=re.IGNORECASE)
    s = re.sub(r"\bJOIN\s+\[?Buying\]?\b", "JOIN [dbo].[buying]", s, flags=re.IGNORECASE)
    return s


def _best_match(name: str, candidates: Set[str]) -> str | None:
    nm = name.lower()
    for c in candidates:
        if c.lower() == nm:
            return c
    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.65)
    return matches[0] if matches else None


def _schema_correct_alias_columns(sql: str, tables: Dict[str, Set[str]]) -> Tuple[str, int]:
    fixes = 0
    s = sql
    for pat, rep in _COMMON_SYNONYMS.items():
        s2 = re.sub(pat, rep, s, flags=re.IGNORECASE)
        if s2 != s:
            fixes += 1
            s = s2
    for pat, rep in _COMMON_TOKENS.items():
        s = re.sub(pat, rep, s, flags=re.IGNORECASE)

    def repl(m: re.Match) -> str:
        nonlocal fixes
        alias, col = m.group(1), m.group(2)
        table = _ALIAS_TABLE.get(alias.lower())
        valid = tables.get(table, set()) if table else set()
        if col in valid:
            return m.group(0)
        if valid:
            sug = _best_match(col, valid)
            if sug:
                fixes += 1
                return f"{alias}.{sug}"
        return m.group(0)

    s = re.sub(r"\b([psb])\.\[?([A-Za-z_]\w*)\]?\b", repl, s)
    return s, fixes


def _fix_incomplete_predicates(sql: str) -> str:
    s = sql
    s = re.sub(
        rf"(\b[psb]\.\[?Date\]?|\bDate\b)\s*(<=|<|>=|>|=)\s*{_BOUNDARY}",
        r"\1 \2 GETDATE() ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        rf"(\b[psb]\.\[?Date\]?|\bDate\b)\s+BETWEEN\s+([^\s]+)\s+AND\s*{_BOUNDARY}",
        r"\1 BETWEEN \2 AND GETDATE() ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(rf"\s+\b(AND|OR)\b\s*{_BOUNDARY}", " ", s, flags=re.IGNORECASE)
    return s


def _inject_top(sql: str) -> str:
    if re.match(r"^\s*select\b", sql, flags=re.IGNORECASE):
        if " top " not in sql.lower():
            return re.sub(r"(?i)^select\s+", "SELECT TOP 200 ", sql, count=1)
    return sql


def _sanitize_sql(sql: str) -> str:
    s = _basic_cleanup(sql)
    s = _normalize_tables(s)
    s = _fix_incomplete_predicates(s)
    tables = _load_schema()
    s, _ = _schema_correct_alias_columns(s, tables)
    s = _inject_top(s)
    if not s.rstrip().endswith(";"):
        s = s.rstrip() + ";"
    return s


def _fallback_sql() -> str:
    """
    Fallback when LLM is not reachable.
    """
    return "SELECT TOP 50 [ProductCode], [ProductName] FROM [dbo].[products];"


def generate_and_execute(question: str, preview_limit: int) -> Dict[str, Any]:
    """
    Main LLM → SQL → DB pipeline.
    If Ollama is not reachable we return a predefined fallback query.
    """
    t0 = time.perf_counter()

    raw_text = None
    model_name = getattr(settings, "ollama_model", None) or "llama3"
    ptok = etok = llm_ms = 0

    # 1) try your existing langchain chain
    if get_few_shot_db_chain is not None:
        try:
            chain = get_few_shot_db_chain()
            start_llm = time.perf_counter()
            res = chain.invoke({"query": question})
            llm_ms = int((time.perf_counter() - start_llm) * 1000)
            raw_text = res.get("result") if isinstance(res, dict) else str(res)
        except Exception as e:
            print(f"[langchain_sql] few_shot chain error: {e}")
            raw_text = None

    # 2) fallback to Ollama if above failed
    if not raw_text:
        prompt = (
            "You are a senior SQL Server engineer. Generate ONLY one T-SQL SELECT.\n\n"
            + _allowed_text()
            + "\nRules:\n"
            "- SQL Server syntax only. No comments, no prose.\n"
            "- Use explicit schema [dbo].\n"
            "- Use aliases: [p]=[dbo].[products], [s]=[dbo].[selling], [b]=[dbo].[buying].\n"
            "- If aggregating, GROUP BY [p].[ProductCode], [p].[ProductName].\n"
            "- End with a semicolon.\n\n"
            f"Question: {question}\n\n"
            "<SQL>\nSELECT ... ;\n</SQL>\n"
        )
        out = generate_with_metrics(
            prompt,
            stop=["</SQL>"],
            timeout_seconds=getattr(settings, "ollama_timeout", 12),
            num_predict=getattr(settings, "ollama_num_predict", 128),
        )

        if out.get("error"):
            # Ollama is down or returned bad JSON → fallback
            print(f"[langchain_sql] Ollama error: {out['error']}")
            sql = _fallback_sql()
            df = pd.read_sql_query(text(sql), get_engine())
            if len(df) > preview_limit:
                df = df.head(preview_limit)
            total_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "sql": sql,
                "columns": list(df.columns),
                "rows": df.to_dict(orient="records"),
                "summary_ar": f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}" + ("..." if len(df.columns) > 6 else ""),
                "model": None,
                "llm_prompt_tokens": 0,
                "llm_eval_tokens": 0,
                "llm_total_tokens": 0,
                "llm_duration_ms": 0,
                "total_ms": total_ms,
            }

        raw_text = out["text"] or ""
        model_name = out.get("model") or model_name
        ptok = int(out.get("prompt_eval_count", 0))
        etok = int(out.get("eval_count", 0))
        llm_ms = int(out.get("total_duration_ms", 0))

    # extract SQL from tags
    m = re.search(r"<SQL>\s*([\s\S]+?)\s*</SQL>", raw_text or "", flags=re.IGNORECASE)
    sql_raw = (m.group(1).strip() if m else raw_text.strip())
    sql = enforce_select_only(sql_raw)
    sql = _sanitize_sql(sql)

    try:
        df = pd.read_sql_query(text(sql), get_engine())
    except Exception as err:
        # guided repair using Ollama again
        fix_prompt = (
            "Fix the following into ONE valid T-SQL SELECT ONLY for SQL Server. "
            "Use ONLY the listed columns. No prose. End with a semicolon.\n\n"
            + _allowed_text()
            + f"\n-- DB error:\n{err}\n\n-- SQL:\n{sql}\n\n"
              "<SQL>\nSELECT ... ;\n</SQL>\n"
        )
        out2 = generate_with_metrics(fix_prompt, stop=["</SQL>"])
        if out2.get("error"):
            print(f"[langchain_sql] repair also failed with Ollama: {out2['error']}")
            sql = _fallback_sql()
        else:
            raw2 = out2["text"] or ""
            m2 = re.search(r"<SQL>\s*([\s\S]+?)\s*</SQL>", raw2, flags=re.IGNORECASE)
            sql2 = enforce_select_only((m2.group(1).strip() if m2 else raw2).strip())
            sql2 = _sanitize_sql(sql2)
            sql = sql2
        df = pd.read_sql_query(text(sql), get_engine())
        ptok += int(out2.get("prompt_eval_count", 0))
        etok += int(out2.get("eval_count", 0))
        llm_ms += int(out2.get("total_duration_ms", 0))

    if len(df) > preview_limit:
        df = df.head(preview_limit)

    total_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "sql": sql,
        "columns": list(df.columns),
        "rows": df.to_dict(orient="records"),
        "summary_ar": (
            f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}"
            + ("..." if len(df.columns) > 6 else "")
        ),
        "model": model_name,
        "llm_prompt_tokens": ptok,
        "llm_eval_tokens": etok,
        "llm_total_tokens": ptok + etok,
        "llm_duration_ms": llm_ms,
        "total_ms": total_ms,
    }
