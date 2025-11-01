# PharmacyDB SQL Q&A
_FastAPI · SQL Server · LangChain (Ollama) · Agents · Frontend · Docker_

A production-oriented, **Arabic-first** service that lets you ask questions about your **PharmacyDB** (SQL Server) and get real SQL results safely.

It supports **three** ways to generate SQL:

1. **Pattern (rule-based):** ultra-fast, deterministic SQL for common pharmacy questions.
2. **LangChain (Ollama):** LLM → T-SQL → sanitize → execute.
3. **Agents:** planner → writer → tester, with **automatic fallback** to the LangChain route.

All routes return the **same JSON shape**, all of them enforce **SELECT-only**, and the project comes with a simple **web UI** at `/app`.

---

## ✨ Key Features

- **3 SQL routes**
  - **/api/pattern** → fastest, no LLM, but only for known questions.
  - **/api/langchain** → LLM via Ollama, strict SQL-only prompt.
  - **/api/agents** → multi-step LLM (plan → write → test) + fallback.
- **Safety**
  - SELECT-only guard (blocks INSERT/UPDATE/DELETE/EXEC/DDL).
  - SQL sanitizer: normalize tables/columns, fix incomplete predicates.
  - TOP injection to avoid huge result sets.
- **DX / UX**
  - Arabic error messages.
  - Uniform response shape (columns + rows + summary + metrics).
  - Preset (important) queries.
- **Docker-ready**
  - App runs in container.
  - Connects to SQL Server on the **Windows host** via `host.docker.internal,1433`.
  - Clear logging of Ollama errors.
- **Configurable**
  - `.env` driven (DB, LLM, CORS, preview size).
  - Can run from project root or from `/app` using `--app-dir ..`.

---

## 🧱 Project Structure

```text
├─ app/
│  ├─ main.py
│  ├─ core/
│  │  └─ config.py
│  ├─ db/
│  │  └─ session.py
│  ├─ routers/
│  │  └─ query.py
│  ├─ services/
│  │  ├─ pattern.py
│  │  ├─ langchain_sql.py
│  │  ├─ agents.py
│  │  └─ ollama_client.py
│  ├─ utils/
│  │  └─ sql_safety.py
│  ├─ schemas/
│  │  ├─ requests.py
│  │  └─ responses.py
│  ├─ presets.py
│  └─ frontend/
│     ├─ index.html
│     └─ app.js
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
└─ .env
└─ .env_example


```

---

## ⚙️ Requirements

- Python 3.10+
- SQL Server (2019/2021/2022) listening on 1433
- ODBC Driver 17 or 18 for SQL Server
- Ollama running locally with a SQL-friendly model

---

## 🔐 Environment (.env)

```env
DB_SERVER=host.docker.internal
DB_PORT=1433
DB_NAME=PharmacyDB
DB_DRIVER={ODBC Driver 18 for SQL Server}
DB_TRUSTED=false
DB_USERNAME=sa
DB_PASSWORD=YourStrong!Passw0rd
DB_ENCRYPT=yes
DB_TRUST_SERVER_CERT=yes
DB_CONNECT_TIMEOUT=15

OLLAMA_MODEL=qwen2.5-coder:latest
OLLAMA_BASE_URL=
OLLAMA_TEMPERATURE=0.0
OLLAMA_NUM_PREDICT=128
OLLAMA_TIMEOUT=45s
OLLAMA_KEEP_ALIVE=15m

CORS_ORIGINS=http://localhost:3000
PREVIEW_LIMIT=200
```

---

## ▶️ Run (local, no Docker)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- UI → http://127.0.0.1:8000/app/
- Docs → http://127.0.0.1:8000/docs
- Health → GET http://127.0.0.1:8000/api/health

---

## 🐳 Docker

1. Make sure SQL Server is listening on 1433 on Windows:

   ```powershell
   netstat -ano | findstr 1433
   ```

2. Allow Windows firewall:

   ```powershell
   netsh advfirewall firewall add rule name="Allow SQL 1433" dir=in action=allow protocol=TCP localport=1433
   ```

3. Build and run:

   ```bash
   docker compose up --build
   ```

4. Open:
   - UI:   http://localhost:8000/app/
   - Docs: http://localhost:8000/docs

**Notes**

- Container reaches SQL Server via `host.docker.internal,1433`
- If Ollama runs on the host → set `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- If Ollama returns bad JSON → app will log it and return a clean API error

---

## 🔗 API Endpoints

- `GET  /api/health`
- `POST /api/pattern`
- `POST /api/langchain`
- `POST /api/agents`
- `POST /api/run-sql`
- `GET  /api/presets`
- `POST /api/presets/run?name=...`

All of them return the same JSON on success:

```json
{
  "route": "langchain",
  "sql": "SELECT TOP 50 ...;",
  "columns": ["ProductCode", "ProductName"],
  "rows": [],
  "summary_ar": "عدد الصفوف المعروضة: 0 | الأعمدة: ProductCode, ProductName",
  "model": "qwen2.5-coder:latest",
  "llm_prompt_tokens": 0,
  "llm_eval_tokens": 0,
  "llm_total_tokens": 0,
  "llm_duration_ms": 0,
  "total_ms": 0,
  "via_fallback": false
}
```
## 🧠 Integrations

- **SQL Server** → main data
- **Ollama** → LLM for langchain + agents
- **Docker** → to run the API in container and still talk to host SQL Server
- **Any frontend** → call JSON
- **Nginx / IIS** → reverse proxy + TLS

---
## 📄 License

Private / internal.
