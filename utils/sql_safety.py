# app/utils/sql_safety.py
import re

# نسمح بـ SELECT أو CTE فقط
_START_OK = re.compile(r"^\s*(SELECT|WITH|;WITH)\b", re.IGNORECASE)

# منع DDL/DML/EXEC
_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|TRUNCATE|CREATE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# إشارات أنه شرح وليس SQL
_NONSQL_HINTS = re.compile(
    r"\b(alias|clause|semicolon|note|tip|explanation|warning|advice)\b",
    re.IGNORECASE,
)

# مرشحات SELECT فقط (حتى أول ;) — لا تلتقط WITH هنا
_SELECT_CAND = re.compile(r"(?is)\bSELECT\b[\s\S]*?;")

# رأس CTE صالح: WITH <name> AS (
_CTE_HEAD = re.compile(r"(?is)^\s*(?:WITH|;WITH)\s+[A-Za-z\[\]_][\w\]\s,]*\s+AS\s*\(", re.IGNORECASE)

# مرشحات WITH…; لكن نقبل فقط إن رأسها مطابق CTE_HEAD
_WITH_CAND = re.compile(r"(?is)\b(?:WITH|;WITH)\b[\s\S]*?;")

# ذيول ناقصة تُحذف قبل ;
_INCOMPLETE_TAIL = re.compile(
    r"""(?ix)
    \s+(?:LEFT|RIGHT|FULL|INNER|OUTER)\s*(?:JOIN)?\s*;$
  | \s+JOIN\s*;$
  | \s+ON\s*;$
  | \s+(?:AND|OR)\s*;$
  | \s+WHERE\s*;$
  | \s+GROUP\s+BY\s*;$
  | \s+ORDER\s+BY\s*;$
  """
)

def _strip_code_fences(s: str) -> str:
    s = re.sub(r"^\s*```(?:sql)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s

def _strip_leading_labels(s: str) -> str:
    # SQLQuery: / SQL: / sql:\n
    s = re.sub(r'^\s*"?(?:SQLQuery|SQL|T-SQL|TSQL)\s*[:\n]\s*', "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*sql\s*\n\s*", "", s, flags=re.IGNORECASE)
    return s

def _trim_incomplete_tail(c: str) -> str:
    return _INCOMPLETE_TAIL.sub(";", c.rstrip())

def _score_candidate(c: str) -> int:
    score = 0
    lc = c.lower()
    if " select " in f" {lc} ":
        score += 40
    if " from " in lc:
        score += 50
    if " join " in lc:
        score += 10
    if len(c) >= 40:
        score += min(len(c) // 50, 20)
    if _NONSQL_HINTS.search(c):
        score -= 100
    # اقتباس غير مغلق
    if c.count("'") % 2 == 1:
        score -= 40
    # ذيل ناقص
    if _INCOMPLETE_TAIL.search(c):
        score -= 20
    return score

def _collect_candidates(text: str) -> list[str]:
    cands = [m.group(0).strip() for m in _SELECT_CAND.finditer(text)]
    # WITH مرشح فقط إذا رأس CTE صحيح
    for m in _WITH_CAND.finditer(text):
        seg = m.group(0).strip()
        head = seg[:140]
        if _CTE_HEAD.search(head):
            cands.append(seg)
    return cands

def _pick_best_sql(text: str) -> str | None:
    cands = _collect_candidates(text)
    if not cands:
        # لا يوجد ; — جرّب SELECT إلى نهاية النص
        m_sel = re.search(r"(?is)\bSELECT\b[\s\S]*", text)
        if m_sel:
            s = m_sel.group(0).strip()
            if not s.endswith(";"):
                s += ";"
            return _trim_incomplete_tail(s)
        # جرّب CTE إلى النهاية بشرط رأس CTE صحيح
        m_w = re.search(r"(?is)\b(?:WITH|;WITH)\b[\s\S]*", text)
        if m_w and _CTE_HEAD.search(text[m_w.start(): m_w.start()+160]):
            s = text[m_w.start():].strip()
            if not s.endswith(";"):
                s += ";"
            return _trim_incomplete_tail(s)
        return None
    best = max(cands, key=_score_candidate)
    return _trim_incomplete_tail(best)

def enforce_select_only(sql_text: str) -> str:
    """يستخرج أفضل استعلام SELECT/CTE صالح ويقص الشرح والأذيال الناقصة ويمنع DML/DDL."""
    if not sql_text or not str(sql_text).strip():
        raise ValueError("SQL فارغ. الرجاء توفير استعلام SELECT/CTE صالح.")

    s = str(sql_text).strip()
    s = _strip_code_fences(s)
    s = _strip_leading_labels(s)

    if not _START_OK.match(s) or _NONSQL_HINTS.search(s):
        chosen = _pick_best_sql(s)
        if not chosen:
            raise ValueError("تعذر استخراج استعلام SELECT/CTE صالح من رد النموذج.")
        s = chosen
    else:
        s = _pick_best_sql(s) or s

    if _BLOCKED.search(s):
        raise ValueError("مسموح فقط بـ SELECT/CTE. تم العثور على DML/DDL/EXEC.")

    if not s.rstrip().endswith(";"):
        s = s.rstrip() + ";"
    return s
