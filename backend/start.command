#!/bin/bash
set -e
cd "$(dirname "$0")"
PG_BIN=/Applications/Postgres.app/Contents/Versions/latest/bin
if ! "$PG_BIN/pg_ctl" -D "$PWD/.postgres" status >/dev/null 2>&1; then
  "$PG_BIN/pg_ctl" -D "$PWD/.postgres" -l "$PWD/.postgres/server.log" start
fi
.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
