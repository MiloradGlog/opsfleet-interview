#!/usr/bin/env bash
# Idempotent boot: wait for Postgres -> seed Trios into pgvector -> start the CLI.
set -euo pipefail

echo "[entrypoint] waiting for Postgres at ${DATABASE_URL} ..."
python - <<'PY'
import os, time, sys
import psycopg
url = os.environ["DATABASE_URL"]
for i in range(60):
    try:
        with psycopg.connect(url, connect_timeout=2) as c:
            c.execute("SELECT 1")
        print("[entrypoint] Postgres is up.")
        sys.exit(0)
    except Exception as e:
        time.sleep(1)
print("[entrypoint] Postgres did not become ready in time.", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] seeding golden_assets (idempotent, real Gemini embeddings) ..."
python -m retail_agent.seed || echo "[entrypoint] seed step reported an issue (continuing)."

# If a one-shot question was passed, run it and exit; otherwise start the REPL.
if [ "$#" -gt 0 ]; then
    exec python -m retail_agent.cli "$@"
else
    echo "[entrypoint] starting interactive CLI. Attach with: docker compose -p p2gamma attach agent"
    exec python -m retail_agent.cli
fi
