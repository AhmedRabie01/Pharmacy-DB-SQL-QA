# app/utils/sql_safety.py
import re

# allow only SELECT or CTE
_START_OK = re.compile(r"^\s*(SELECT|WITH|;WITH)\b", re.IGNORECASE)

# block DDL/DML/EXEC
_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|TRUNCATE|CREATE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# markers that the text is explanation, not SQL
_NONSQL_HINTS = re.compile(
    r"\b(alias|clause|semicolon|note|tip|explanation|warning|advice)\b",
    re.IGNORECASE,
)

# SELECT candidates (up to first ;)
_SELECT_CAND = re.compile(r"(?is)\bSELECT\b[\s\S]*?;")

# valid CTE head
_CTE_HEAD = re.compile(r"(?is)^\s*(?:WITH|;WITH)\s+[A-Za-z\[\]_][\w\]\s,]*\s+AS\s*\(", re.IGNORECASE)

# WITH candidates, but only if head matches
_WITH_CAND = re.compile(r"(?is)\b(?:WITH|;WITH)\b[\s\S]*?;")

# incomplete endings we should trim
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
    # unclosed quote
    if c.count("'") % 2 == 1:
        score -= 40
    # incomplete tail
    if _INCOMPLETE_TAIL.search(c):
        score -= 20
    return score


def _collect_candidates(text: str) -> list[str]:
    cands = [m.group(0).strip() for m in _SELECT_CAND.finditer(text)]
    # also try WITH if the head looks valid
    for m in _WITH_CAND.finditer(text):
        seg = m.group(0).strip()
        head = seg[:140]
        if _CTE_HEAD.search(head):
            cands.append(seg)
    return cands


def _pick_best_sql(text: str) -> str | None:
    cands = _collect_candidates(text)
    if not cands:
        # no semicolon → try SELECT to end
        m_sel = re.search(r"(?is)\bSELECT\b[\s\S]*", text)
        if m_sel:
            s = m_sel.group(0).strip()
            if not s.endswith(";"):
                s += ";"
            return _trim_incomplete_tail(s)
        # try CTE to end if head is valid
        m_w = re.search(r"(?is)\b(?:WITH|;WITH)\b[\s\S]*", text)
        if m_w and _CTE_HEAD.search(text[m_w.start(): m_w.start() + 160]):
            s = text[m_w.start():].strip()
            if not s.endswith(";"):
                s += ";"
            return _trim_incomplete_tail(s)
        return None
    best = max(cands, key=_score_candidate)
    return _trim_incomplete_tail(best)


def enforce_select_only(sql_text: str) -> str:
    """
    Extract the best valid SELECT/CTE and block DML/DDL.
    """
    if not sql_text or not str(sql_text).strip():
        raise ValueError("Empty SQL. Please provide a valid SELECT/CTE.")

    s = str(sql_text).strip()
    s = _strip_code_fences(s)
    s = _strip_leading_labels(s)

    if not _START_OK.match(s) or _NONSQL_HINTS.search(s):
        chosen = _pick_best_sql(s)
        if not chosen:
            raise ValueError("Could not extract a valid SELECT/CTE from LLM response.")
        s = chosen
    else:
        s = _pick_best_sql(s) or s

    if _BLOCKED.search(s):
        raise ValueError("Only SELECT/CTE is allowed. DML/DDL/EXEC found.")

    if not s.rstrip().endswith(";"):
        s = s.rstrip() + ";"

    return s
