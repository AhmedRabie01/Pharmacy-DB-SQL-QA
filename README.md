# PharmacyDB SQL Q&A (FastAPI · LangChain/Ollama · Agents · Frontend)

A production‑grade, Arabic‑first app to query a SQL Server **PharmacyDB** safely using three routes:

- **Pattern (Rule-based)**: ultra-fast, curated SQL templates for common asks.
- **LangChain (Ollama)**: strict SQL‑only prompting with sanitization & metrics.
- **Agents (optional)**: planner → writer → tester with safe execution & fallback.

The app exposes a clean **REST API** and a lightweight **web UI**. It enforces **SELECT‑only**, returns **metrics** (tokens & timings), and includes an **Important Queries** pack (analytics presets).

---

## ✨ Features

- **3 Generation Routes**
  - Pattern (fast & deterministic)
  - LangChain (LLM via Ollama, strict SQL‑only)
  - Agents (planner/writer/tester with fallback to LangChain)
- **Safety First**
  - `SELECT`‑only enforcement
  - SQL sanitizer: fixes table/column aliases & common mistakes
  - TOP N injection for large result-sets
- **DX / UX**
  - Arabic‑first responses & errors
  - Consistent success payload across routes
  - Token counts & timing metrics (`llm_total_tokens`, `llm_duration_ms`, `total_ms`)
  - Presets (ready analytics SQL)
- **Deployment Friendly**
  - `.env` driven config (DB + LLM + API)
  - Robust static files mount
  - Works from **project root** and **/app** with `--app-dir ..`

---

## 🧱 Project Structure

```
app/
├─ __init__.py
├─ main.py
├─ core/
│  ├─ __init__.py
│  └─ config.py                 # env-driven settings (+ s/m/h duration parsing)
├─ db/
│  ├─ __init__.py
│  └─ session.py                # SQLAlchemy engine (SQL Server/pyodbc)
├─ routers/
│  ├─ __init__.py
│  └─ query.py                  # unified endpoints: pattern / langchain / agents / sql / presets
├─ schemas/
│  ├─ __init__.py
│  ├─ requests.py               # Pydantic request models
│  └─ responses.py              # Pydantic response models (uniform payload)
├─ services/
│  ├─ __init__.py
│  ├─ pattern.py                # rule-based SQL generator (Arabic/English triggers)
│  ├─ langchain_sql.py          # LangChain + Ollama strict SQL-only chain
│  ├─ agents.py                 # planner → writer → tester orchestrator
│  ├─ llm.py                    # shared LLM helpers (prompts/extractors)
│  └─ ollama_client.py          # raw Ollama HTTP client + timeouts/metrics
├─ utils/
│  ├─ __init__.py
│  └─ sql_safety.py             # SELECT-only guard, TOP injection, common fixes
├─ frontend/
│  ├─ index.html                # lightweight static UI served at /app
│  └─ app.js
├─ presets.py                   # Important Queries (analytics pack)
├─ .env_example                 # sample env (no secrets)
├─ README.md
└─ requirements.txt

```

> **Note**: The app supports starting from root (`uvicorn app.main:app`) and from `/app` using `--app-dir ..`.

---

## ⚙️ Requirements

- Python 3.10+
- SQL Server with ODBC Driver 17 (Windows)  
- Ollama (local LLM server) with a compatible model (e.g., `qwen2.5-coder:latest`)

**Python packages (excerpt):**
```
fastapi uvicorn pydantic pydantic-settings sqlalchemy pyodbc pandas
langchain-community httpx
```

---

## 🔐 Environment (.env)

See `.env_example` for all keys. Highlights:

```env
# DB
DB_SERVER=.
DB_NAME=PharmacyDB
DB_DRIVER={ODBC Driver 17 for SQL Server}
DB_TRUSTED=true
DB_USERNAME=
DB_PASSWORD=

# LLM (Ollama)
OLLAMA_MODEL=qwen2.5-coder:latest
OLLAMA_BASE_URL=           # empty -> http://127.0.0.1:11434
OLLAMA_TEMPERATURE=0.0
OLLAMA_NUM_PREDICT=128
OLLAMA_TIMEOUT=10m         # accepts 30 / 45s / 10m / 1h
OLLAMA_KEEP_ALIVE=15m      # accepts s/m/h

# API
CORS_ORIGINS=http://localhost:3000
PREVIEW_LIMIT=200
```

> Durations like `10m`/`15m` are parsed into seconds by `app/core/config.py` validators.

---

## ▶️ Run

### Option A — from **project root** (recommended)
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Option B — from inside **/app**
```bash
uvicorn --app-dir .. app.main:app --reload --host 127.0.0.1 --port 8000
```

> Health check: `GET http://127.0.0.1:8000/api/health` (if present).  
> Open UI (if bundled): `http://127.0.0.1:8000/app/`

---

## 🔗 API (Success Response Shape)

All generation routes return the **same JSON** on success:

```json
{
  "sql": "SELECT TOP 10 ...;",
  "columns": ["ProductCode", "ProductName", "TotalSold"],
  "rows": [{ "ProductCode": "A1", "ProductName": "Panadol", "TotalSold": 325 }],
  "summary_ar": "عدد الصفوف المعروضة: 10 | الأعمدة: ProductCode, ProductName, TotalSold",
  "model": "qwen2.5-coder:latest",
  "llm_prompt_tokens": 42,
  "llm_eval_tokens": 128,
  "llm_total_tokens": 170,
  "llm_duration_ms": 180,
  "total_ms": 360,
  "via_fallback": false
}
```

**Error response:**

```json
{ "detail": "رسالة خطأ عربية واضحة بدون stack trace..." }
```

### Endpoints (examples)
- `POST /api/pattern` → `{ question }` → SQL + results (204 if no pattern match)
- `POST /api/langchain` → `{ question }` → SQL + results
- `POST /api/agents` → `{ question }` → SQL + results (fallback to langchain on timeout)
- `POST /api/sql` → `{ sql }` → execute a manual SELECT safely
- `GET  /api/presets` → list of preset queries
- `GET  /api/presets/{id}` → preset SQL

---

## 🛡️ Safety & SQL Rules

- **SELECT‑only**: requests with non‑SELECT are rejected server‑side.
- **Sanitizer**: fixes common issues (wrong column name synonyms, incomplete date conditions, missing `TOP`, etc.).
- **Aliases & GROUP BY**: enforced for joins/aggregations to ensure stable columns.

> Tip: If you pass a bad column (e.g., `QuantitySelling`), the sanitizer maps it to `QuantitySold` or returns a clean error in Arabic.

---

## 🧠 LLM / Agents

- **LangChain** uses `langchain_community.llms.Ollama` with a strict SQL‑only prompt and extraction (regex).
- **Agents** (optional) orchestrate planner → writer → tester with hard timeouts and **automatic fallback** to LangChain if the LLM stalls or doesn’t return valid SQL.

> Metrics are gathered from Ollama responses and wall‑clock timers; returned to the client for observability.

---

## 📊 Presets (Important Queries Pack)

Examples included:
- Monthly revenue
- Top 10 products by revenue
- Bought-not-sold in the last 90 days
- Store performance by revenue
- Low stock alerts (`Quantity <= 5`)

Use `/api/presets` or run preset SQL through `/api/sql` (manual executor).

---

## 🚀 Deployment Notes

- **Reverse proxy**: Serve via Nginx/IIS for TLS & compression.
- **Windows service**: Use NSSM or `pywin32` to run Uvicorn as a service.
- **Logging**: Log Arabic errors and a compact per‑request timing; avoid stack traces in responses.
- **CORS**: Restrict `CORS_ORIGINS` on production.

---

## 🧪 Testing

- **Unit**: patterns → expected SQL; safety rejects non‑SELECT; sanitizer mappings.
- **Integration**: real DB with a small fixture; confirm result shapes & metrics.
- **Load**: 10–20 concurrent users; monitor `total_ms` and error rate (<1%).

---


## 📄 License

Proprietary — internal use only (customize to your needs).

---

## 🙌 Credits

- FastAPI, Pydantic v2, SQLAlchemy, Pandas  
- LangChain Community + Ollama  
- Everyone who loves clean APIs and safe SQL 😄

