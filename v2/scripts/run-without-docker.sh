#!/usr/bin/env bash
# Run the whole demo on this machine without Docker.
#
#   scripts/run-without-docker.sh start    set everything up on first use, then start it
#   scripts/run-without-docker.sh stop     stop the web app, the API and the private database
#   scripts/run-without-docker.sh status   show what is running
#   scripts/run-without-docker.sh reset    restore the seeded demo data
#   scripts/run-without-docker.sh logs     follow the API and web logs
#
# Needs: Python 3.12, Node.js 20 or later, PostgreSQL 17 (on a Mac: brew install python@3.12 postgresql@17).
# Everything it creates lives in ./.local, including its own database on its own port, so it
# never touches any other PostgreSQL on this machine. Delete ./.local to start from nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="$ROOT/.local"
PG_PORT="${PG_PORT:-5544}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
DB_NAME="renewi_access"
DB_USER="renewi"

export LC_ALL="${LC_ALL:-en_US.UTF-8}" LANG="${LANG:-en_US.UTF-8}" PYTHONDONTWRITEBYTECODE=1

fail() { echo "error: $*" >&2; exit 1; }

find_postgres_bin() {
  local candidate
  for candidate in "$(brew --prefix postgresql@17 2>/dev/null || true)/bin" /opt/homebrew/opt/postgresql@17/bin /usr/local/opt/postgresql@17/bin; do
    [ -x "$candidate/pg_ctl" ] && { echo "$candidate"; return; }
  done
  command -v pg_ctl >/dev/null 2>&1 && { dirname "$(command -v pg_ctl)"; return; }
  fail "PostgreSQL 17 was not found. On a Mac: brew install postgresql@17"
}

find_python() {
  local candidate
  for candidate in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    command -v "$candidate" >/dev/null 2>&1 && { command -v "$candidate"; return; }
  done
  fail "Python 3.12 was not found. On a Mac: brew install python@3.12"
}

pg_up() { "$PGBIN/pg_isready" -q -h 127.0.0.1 -p "$PG_PORT"; }
psql_db() { "$PGBIN/psql" -X -q -h 127.0.0.1 -p "$PG_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"; }

api_env() {
  export PYTHONPATH="$ROOT/services/api"
  export APP_ENV=development LOG_LEVEL=INFO
  export DATABASE_URL="postgresql+psycopg://$DB_USER@127.0.0.1:$PG_PORT/$DB_NAME"
  export WEB_ORIGIN="http://localhost:$WEB_PORT"
  export DEMO_MODE=true DEMO_TIMEZONE=Europe/Amsterdam
  export SESSION_COOKIE_SECURE=false SESSION_COOKIE_NAME=renewi_session SESSION_TTL_SECONDS=28800
  export STORAGE_PROVIDER=local STORAGE_LOCAL_PATH="$LOCAL/evidence"
  export OCR_PROVIDER=mock IDENTITY_VERIFIER_PROVIDER=mock NOTIFICATION_PROVIDER=mock AUTH_PROVIDER=demo
  export BACKEND_PORT="$API_PORT"
  # The demo-only password lives in .env.example; it is not a real credential.
  DEMO_SEED_PASSWORD="$(grep '^DEMO_SEED_PASSWORD=' "$ROOT/.env.example" | cut -d= -f2-)"
  export DEMO_SEED_PASSWORD
}

kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

stop_pid() {
  local file="$LOCAL/$1.pid"
  [ -f "$file" ] || return 0
  local pid; pid="$(cat "$file")"
  # npm starts child processes, so stop the whole tree, not just the first process.
  if kill -0 "$pid" 2>/dev/null; then kill_tree "$pid"; fi
  rm -f "$file"
}

# Start a server fully detached from this terminal, so this script can return.
start_detached() {
  local name="$1" dir="$2"; shift 2
  ( cd "$dir" && exec "$@" ) >"$LOCAL/$name.log" 2>&1 </dev/null &
  echo $! >"$LOCAL/$name.pid"
}

running() { [ -f "$LOCAL/$1.pid" ] && kill -0 "$(cat "$LOCAL/$1.pid")" 2>/dev/null; }

cmd_start() {
  command -v node >/dev/null 2>&1 || fail "Node.js was not found. On a Mac: brew install node"
  PGBIN="$(find_postgres_bin)"; PY="$(find_python)"
  mkdir -p "$LOCAL/evidence"

  if [ ! -x "$LOCAL/venv/bin/python" ]; then
    echo "Creating the Python environment..."
    "$PY" -m venv "$LOCAL/venv"
  fi
  if [ ! -f "$LOCAL/venv/.installed" ]; then
    echo "Installing the API's packages..."
    "$LOCAL/venv/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/services/api/requirements.lock"
    touch "$LOCAL/venv/.installed"
  fi
  if [ ! -d "$ROOT/apps/web/node_modules" ]; then
    echo "Installing the web app's packages (about a minute)..."
    (cd "$ROOT/apps/web" && npm ci --no-audit --no-fund --silent)
  fi

  if [ ! -d "$LOCAL/pgdata" ]; then
    echo "Creating the private database..."
    "$PGBIN/initdb" -D "$LOCAL/pgdata" -U "$DB_USER" --auth=trust -E UTF8 --locale="$LC_ALL" >/dev/null
  fi
  if ! pg_up; then
    "$PGBIN/pg_ctl" -D "$LOCAL/pgdata" -l "$LOCAL/postgres.log" -w \
      -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=" start >/dev/null
  fi
  if [ "$("$PGBIN/psql" -X -At -h 127.0.0.1 -p "$PG_PORT" -U "$DB_USER" -d postgres -c "select 1 from pg_database where datname='$DB_NAME'")" != "1" ]; then
    "$PGBIN/createdb" -h 127.0.0.1 -p "$PG_PORT" -U "$DB_USER" "$DB_NAME"
  fi

  api_env
  echo "Applying migrations and loading the demo data..."
  (cd "$ROOT/services/api" && "$LOCAL/venv/bin/python" -m app.commands migrate >/dev/null 2>&1 && "$LOCAL/venv/bin/python" -m app.commands seed)

  if ! running api; then
    start_detached api "$ROOT/services/api" "$LOCAL/venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
  fi
  if ! running web; then
    export API_INTERNAL_BASE_URL="http://127.0.0.1:$API_PORT" NEXT_PUBLIC_API_BASE_URL="" \
      PORT="$WEB_PORT" HOSTNAME=127.0.0.1 NEXT_TELEMETRY_DISABLED=1
    start_detached web "$ROOT/apps/web" npm run dev
  fi

  printf "Waiting for the app"
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 && curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT/" 2>/dev/null; then
      echo
      echo "Ready.   Open http://localhost:$WEB_PORT"
      echo "Sign in as admin.demo. The demo password is already filled in on the sign-in page."
      echo "Stop it any time with: scripts/run-without-docker.sh stop"
      return
    fi
    printf "."; sleep 2
  done
  echo; fail "it did not become ready. See $LOCAL/api.log and $LOCAL/web.log"
}

cmd_stop() {
  PGBIN="$(find_postgres_bin)"
  stop_pid web; stop_pid api
  if [ -d "$LOCAL/pgdata" ] && pg_up; then "$PGBIN/pg_ctl" -D "$LOCAL/pgdata" -m fast -w stop >/dev/null; fi
  echo "Stopped."
}

cmd_status() {
  PGBIN="$(find_postgres_bin)"
  running web && echo "web:      running  http://localhost:$WEB_PORT" || echo "web:      stopped"
  running api && echo "api:      running  http://localhost:$API_PORT/docs" || echo "api:      stopped"
  pg_up && echo "database: running  port $PG_PORT" || echo "database: stopped"
}

cmd_reset() {
  PGBIN="$(find_postgres_bin)"; pg_up || fail "start it first: scripts/run-without-docker.sh start"
  api_env
  (cd "$ROOT/services/api" && "$LOCAL/venv/bin/python" -m app.commands reset && "$LOCAL/venv/bin/python" -m app.commands seed)
  echo "Demo data restored."
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  reset) cmd_reset ;;
  logs) tail -n 40 -f "$LOCAL/api.log" "$LOCAL/web.log" ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
