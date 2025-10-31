#!/usr/bin/env bash
set -euo pipefail

DB_HOST="${DB_SERVER:-host.docker.internal,1433}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"

MAX_WAIT_DB=${MAX_WAIT_DB:-120}         # seconds
MAX_WAIT_OLLAMA=${MAX_WAIT_OLLAMA:-120} # seconds

echo "[wait] DB: ${DB_HOST}"
echo "[wait] Ollama: ${OLLAMA_URL}"

# wait for DB (need sqlcmd from mssql-tools18)
echo "[wait] waiting for SQL Server..."
end=$((SECONDS+MAX_WAIT_DB))
until sqlcmd -S "${DB_HOST}" -U "${DB_USERNAME}" -P "${DB_PASSWORD}" -Q "SELECT 1" -b -l 3 >/dev/null 2>&1; do
  if [ $SECONDS -ge $end ]; then
    echo "[wait][DB] timeout after ${MAX_WAIT_DB}s"
    exit 1
  fi
  echo "[wait][DB] not ready, retrying..."
  sleep 2
done
echo "[wait][DB] OK"

# wait for Ollama HTTP
echo "[wait] waiting for Ollama HTTP..."
end=$((SECONDS+MAX_WAIT_OLLAMA))
until curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; do
  if [ $SECONDS -ge $end ]; then
    echo "[wait][Ollama] timeout after ${MAX_WAIT_OLLAMA}s"
    exit 1
  fi
  echo "[wait][Ollama] not ready, retrying..."
  sleep 2
done
echo "[wait][Ollama] OK"

echo "[wait] all deps ready. starting API..."
exec "$@"
