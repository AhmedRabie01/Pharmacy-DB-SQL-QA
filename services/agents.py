# app/services/agents.py
from __future__ import annotations

import os
import re
import time
import difflib
import pandas as pd
from typing import Dict, Any, Set, Tuple, Optional
from sqlalchemy import text

from app.db.session import get_engine
from app.core.config import settings
from app.utils.sql_safety import enforce_select_only
from app.services.ollama_client import generate_with_metrics
from app.services.langchain_sql import generate_and_execute as lc_generate_and_execute

# behavior flags
AGENTS_EAGER_LOAD = os.getenv("AGENTS_EAGER_LOAD", "false").lower() == "true"
AGENTS_SCHEMA_RETRY = int(os.getenv("AGENTS_SCHEMA_RETRY", "0"))

_SQL_END = re.compile(r";\s*$")
_RX_SELECT_OR_WITH = re.compile(r"^\s*(select|with|;with)\b", re.IGNORECASE | re.DOTALL)
_TAG_BLOCK = re.compile(r"<SQL>\s*([\s\S]+?)\s*</SQL>", re.IGNORECASE)
_TRIPLE_SQL = re.compile(r"```sql\s*([\s\S]+?)```", re.IGNORECASE)
_TRIPLE_ANY = re.compile(r"```\s*([\s\S]+?)```", re.IGNORECASE)
_SQLQUERY_LINE = re.compile(r"SQLQuery:\s*(SELECT[\s\S]+?;)", re.IGNORECASE)
_FIRST_SELECT_SEMI = re.compile(r"(SELECT[\s\S]+?;)", re.IGNORECASE)
_FIRST_SELECT_ANY = re.compile(r"(SELECT[\s\S]+)$", re.IGNORECASE)
_FIRST_WITH_BLOCK = re.compile(r"((?:;?\s*WITH|WITH)\s+[\s\S]+?SELECT[\s\S]+?;)", re.IGNORECASE)

_SCHEMA_CACHE: Dict[str, Set[str]] = {}


def _load_schema(timeout_s: int = 0) -> Dict[str, Set[str]]:
    """
    Load schema once. Non-fatal if DB is not ready yet.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE:
        return _SCHEMA_CACHE

    deadline = time.time() + max(0, timeout_s)
    last_err = None
    q = """
    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN ('products','selling','buying');
    """
    while True:
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(text(q)).fetchall()
            tables: Dict[str, Set[str]] = {"products": set(), "selling": set(), "buying": set()}
            for sch, tn, col in rows:
                tables[tn.lower()].add(col)
            _SCHEMA_CACHE = tables
            return tables
        except Exception as e:
            last_err = e
            if time.time() >= deadline:
                print(f"[agents] schema load failed (non-fatal): {e}")
                return {}


def _allowed_columns_text(tables: Dict[str, Set[str]]) -> str:
    if not tables:
        return "Use only tables: [dbo].[products], [dbo].[selling], [dbo].[buying]."
    return (
        "Tables and columns (use ONLY these exact names):\n"
        f"- products: {', '.join(sorted(tables['products']))}\n"
        f"- selling : {', '.join(sorted(tables['selling']))}\n"
        f"- buying  : {', '.join(sorted(tables['buying']))}\n"
    )


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
    s = re.sub(r"^\s*\[?SQL\]?\s*:\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("`", "'")
    s = re.sub(r"'\s*(AND|OR)\b", r"' \1", s, flags=re.IGNORECASE)
    s = re.sub(r"GETDATE\(\s*-\s*(\d+)\s*\)", r"DATEADD(day, -\1, GETDATE())", s, flags=re.IGNORECASE)
    s = re.sub(r"['\"]\s*;$", ";", s)
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


def _best_match(name: str, candidates: Set[str]) -> Optional[str]:
    nm = name.lower()
    for c in candidates:
        if c.lower() == nm:
            return c
    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.65)
    return matches[0] if matches else None


def _detect_products_alias(sql: str) -> str:
    for pat in [
        r"\bFROM\s+\[dbo\]\.\[products\]\s+(?:AS\s+)?([A-Za-z]\w*)",
        r"\bJOIN\s+\[dbo\]\.\[products\]\s+(?:AS\s+)?([A-Za-z]\w*)",
    ]:
        m = re.search(pat, sql, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return "p"


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
        r"(\b[psb]\.\[?Date\]?|\bDate\b)\s*(<=|<|>=|>|=)\s*(?=(?:AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|JOIN|UNION|;|$))",
        r"\1 \2 GETDATE() ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"(\b[psb]\.\[?Date\]?|\bDate\b)\s+BETWEEN\s+([^\s]+)\s+AND\s*(?=(?:AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|JOIN|UNION|;|$))",
        r"\1 BETWEEN \2 AND GETDATE() ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+\b(AND|OR)\b\s*(?=(?:AND|OR|GROUP\s+BY|ORDER\s+BY|HAVING|JOIN|UNION|;|$))", " ", s, flags=re.IGNORECASE)
    return s


def _inject_top(sql: str) -> str:
    if re.match(r"^\s*select\b", sql, flags=re.IGNORECASE):
        if " top " not in sql.lower():
            return re.sub(r"(?i)^select\s+", "SELECT TOP 200 ", sql, count=1)
    return sql


def _enforce_group_by(sql: str) -> str:
    has_aggr = re.search(r"\b(SUM|AVG|COUNT|MIN|MAX)\s*\(", sql, flags=re.IGNORECASE) is not None
    has_group = re.search(r"\bGROUP\s+BY\b", sql, flags=re.IGNORECASE) is not None
    if has_aggr and not has_group:
        alias = _detect_products_alias(sql)
        if not re.search(rf"\b{alias}\.\[?ProductCode\]?\b", sql, flags=re.IGNORECASE):
            sql = re.sub(r"(?i)^select\s+", f"SELECT {alias}.[ProductCode], ", sql, count=1)
        if not re.search(rf"(?i)\b{alias}\.\[?ProductName\]?\b", sql):
            sql = re.sub(
                rf"(?i){alias}\.\[?ProductCode\]?\s*,\s*",
                f"{alias}.[ProductCode], {alias}.[ProductName], ",
                sql,
                count=1,
            )
        grp = f" GROUP BY {alias}.[ProductCode], {alias}.[ProductName] "
        if re.search(r"(?i)\border\s+by\b", sql):
            sql = re.sub(r"(?i)\border\s+by\b", grp + "ORDER BY", sql, count=1)
        else:
            sql = sql.rstrip(";") + grp + ";"
    return sql


def _sanitize_sql(sql: str) -> str:
    s = _basic_cleanup(sql)
    s = _normalize_tables(s)
    s = _fix_incomplete_predicates(s)
    tables = _load_schema(timeout_s=0)
    s, _ = _schema_correct_alias_columns(s, tables)
    s = _inject_top(s)
    s = _enforce_group_by(s)
    if not s.rstrip().endswith(";"):
        s = s.rstrip() + ";"
    return s


def _extract_sql_any(text_: str) -> Optional[str]:
    if not text_:
        return None
    t = text_.strip()
    for rx in (_TAG_BLOCK, _TRIPLE_SQL, _TRIPLE_ANY):
        m = rx.search(t)
        if m:
            return m.group(1).strip()
    m = _SQLQUERY_LINE.search(t)
    if m:
        return m.group(1).strip()
    m = _FIRST_SELECT_SEMI.search(t)
    if m:
        return m.group(1).strip()
    m = _FIRST_WITH_BLOCK.search(t)
    if m:
        return m.group(1).strip()
    m = _FIRST_SELECT_ANY.search(t)
    if m:
        return m.group(1).strip()
    return None


def _rewrite_cte_to_select(raw: str, timeout_s: float, num_predict: int) -> str:
    prompt = (
        "Rewrite the following T-SQL into ONE single SELECT statement (NO CTE/NO WITH). "
        "SQL Server syntax. No prose. End with a semicolon.\n\n"
        f"{raw}\n\n"
        "<SQL>\nSELECT ... ;\n</SQL>\n"
    )
    out = generate_with_metrics(prompt, timeout_seconds=timeout_s, num_predict=num_predict)
    if out.get("error"):
        raise ValueError(f"LLM did not return SQL (rewrite): {out['error']}")
    ex = _extract_sql_any(out["text"])
    if not ex:
        raise ValueError("LLM did not return SQL (rewrite)")
    return ex


def _parse_timeout(v: Optional[str]) -> float:
    try:
        from app.services.ollama_client import _ollama_base_url  # noqa
        # use env-like time or default
        return float(v.replace("s", "")) if v else 12.0
    except Exception:
        return 12.0


class AgentOrchestrator:
    """
    Planner → Writer → Tester.
    Falls back to langchain_sql.generate_and_execute() on any LLM/Ollama error.
    """

    def __init__(self) -> None:
        self.metrics: Dict[str, Any] = {
            "model": None,
            "prompt_tokens": 0,
            "eval_tokens": 0,
            "llm_duration_ms": 0,
            "wall_ms": 0,
        }
        self._allowed_text: Optional[str] = None

        self.agent_timeout_s = float(_parse_timeout(getattr(settings, "OLLAMA_AGENT_TIMEOUT", "8s")))
        self.hard_deadline_s = float(_parse_timeout(getattr(settings, "AGENTS_HARD_DEADLINE", "14s")))
        self.num_predict = int(getattr(settings, "ollama_num_predict", 96))

        if AGENTS_EAGER_LOAD and AGENTS_SCHEMA_RETRY > 0:
            tables = _load_schema(timeout_s=AGENTS_SCHEMA_RETRY)
            self._allowed_text = _allowed_columns_text(tables)

    def _ensure_allowed_text(self) -> None:
        if self._allowed_text is None:
            tables = _load_schema(timeout_s=0)
            self._allowed_text = _allowed_columns_text(tables)

    def _acc(self, m: Dict[str, Any]) -> None:
        if not self.metrics["model"] and m.get("model"):
            self.metrics["model"] = m["model"]
        self.metrics["prompt_tokens"] += int(m.get("prompt_eval_count", 0))
        self.metrics["eval_tokens"] += int(m.get("eval_count", 0))
        self.metrics["llm_duration_ms"] += int(m.get("total_duration_ms", 0))

    def _call_llm(self, prompt: str, start_t: float) -> str:
        if (time.perf_counter() - start_t) >= self.hard_deadline_s:
            raise TimeoutError("agents budget exceeded")

        out = generate_with_metrics(
            prompt,
            timeout_seconds=self.agent_timeout_s,
            num_predict=self.num_predict,
        )
        if out.get("error"):
            raise RuntimeError(f"Ollama returned error: {out['error']}")
        self._acc(out)
        return (out.get("text") or "").strip()

    def _planner(self, question: str, start_t: float) -> str:
        self._ensure_allowed_text()
        prompt = (
            "You are a BI planner for a Pharmacy SQL Server DB.\n"
            "Return a compact plan (bullets): tables, key columns, filters.\n\n"
            f"{self._allowed_text}\n"
            f"Question: {question}\n\n"
            "Plan:"
        )
        return self._call_llm(prompt, start_t)

    def _writer(self, question: str, plan: str, start_t: float) -> str:
        self._ensure_allowed_text()
        prompt = (
            "You are a senior SQL Server engineer.\n"
            f"{self._allowed_text}"
            "Rules:\n"
            "- Output ONE valid T-SQL SELECT ONLY. SQL Server syntax.\n"
            "- NO CTE. No temp tables. No comments. No prose.\n"
            "- Use explicit schema [dbo].\n"
            "- Use aliases: [p]=[dbo].[products], [s]=[dbo].[selling], [b]=[dbo].[buying].\n"
            "- If aggregating, GROUP BY [p].[ProductCode], [p].[ProductName].\n"
            "- End with a semicolon.\n\n"
            f"Plan:\n{plan}\n\n"
            f"Question: {question}\n\n"
            "Return ONLY inside tags:\n<SQL>\nSELECT ... ;\n</SQL>\n"
        )
        raw = self._call_llm(prompt, start_t)
        extracted = _extract_sql_any(raw)
        if not extracted:
            raise ValueError("LLM did not return SQL")
        if extracted.lstrip().lower().startswith(("with", ";with")):
            extracted = _rewrite_cte_to_select(extracted, self.agent_timeout_s, self.num_predict)
        sql = enforce_select_only(extracted if extracted.endswith(";") else extracted + ";")
        sql = _sanitize_sql(sql)
        if not _SQL_END.search(sql):
            sql += ";"
        return sql

    def _tester(self, sql: str, start_t: float) -> str:
        self._ensure_allowed_text()
        sql0 = _sanitize_sql(sql)
        if not _RX_SELECT_OR_WITH.match(sql0):
            prompt = (
                "Fix this into ONE valid T-SQL SELECT ONLY for SQL Server. "
                "NO CTE. No prose. End with a semicolon.\n\n"
                f"{self._allowed_text}\n"
                f"{sql0}\n\n"
                "<SQL>\nSELECT ... ;\n</SQL>\n"
            )
            raw = self._call_llm(prompt, start_t)
            extracted = _extract_sql_any(raw)
            if not extracted:
                raise ValueError("LLM did not return SQL (tester)")
            if extracted.lstrip().lower().startswith(("with", ";with")):
                extracted = _rewrite_cte_to_select(extracted, self.agent_timeout_s, self.num_predict)
            sql0 = enforce_select_only(extracted if extracted.endswith(";") else extracted + ";")
        return _sanitize_sql(sql0)

    def run(self, question: str, preview_limit: int) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            plan = self._planner(question, start)
            if (time.perf_counter() - start) >= self.hard_deadline_s:
                raise TimeoutError("agents budget exceeded after planner")

            raw_sql = self._writer(question, plan, start)
            if (time.perf_counter() - start) >= self.hard_deadline_s:
                raise TimeoutError("agents budget exceeded after writer")

            final_sql = self._tester(raw_sql, start)

            safe_sql = enforce_select_only(final_sql)
            df = pd.read_sql_query(text(safe_sql), get_engine())
            if len(df) > preview_limit:
                df = df.head(preview_limit)

            total_ms = int((time.perf_counter() - start) * 1000)
            self.metrics["wall_ms"] = total_ms

            return {
                "sql": safe_sql,
                "plan": plan,
                "columns": list(df.columns),
                "rows": df.to_dict(orient="records"),
                "summary_ar": (
                    f"Rows: {len(df)} | columns: {', '.join(df.columns[:6])}"
                    + ("..." if len(df.columns) > 6 else "")
                ),
                "model": self.metrics["model"],
                "llm_prompt_tokens": self.metrics["prompt_tokens"],
                "llm_eval_tokens": self.metrics["eval_tokens"],
                "llm_total_tokens": self.metrics["prompt_tokens"] + self.metrics["eval_tokens"],
                "llm_duration_ms": self.metrics["llm_duration_ms"],
                "total_ms": total_ms,
            }

        except Exception as e:
            # hard fallback to langchain route (which also has Ollama fallback now)
            print(f"[agents] error, using langchain fallback: {e}")
            res = lc_generate_and_execute(question, preview_limit)
            res["via_fallback"] = True
            return res


_orchestrator: Optional[AgentOrchestrator] = None


def get_agents() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
