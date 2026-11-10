#!/usr/bin/env bash
# make demo: the API in artifacts mode (published models) and the built web, one command, Ctrl-C stops both (AT-060).
#
#   API  http://127.0.0.1:8000  (docs at /docs)      web  http://127.0.0.1:4173
#
# The web proxies /api to the API through ATLAS_API_URL (apps/web/vite.config.ts), which this script points at API_PORT.
# API_PORT and WEB_PORT can change (a second instance next to a running demo: API_PORT=8020 WEB_PORT=4180).
# The API runs with ATLAS_API_WORKERS uvicorn workers (default 2; AT-061: one worker serves requests in series because
# of the GIL). Each worker is a process with its own caches (docs/api.md). No --reload here: `make api` has it.
# No credentials, no paid services. The basemap tiles come from OpenFreeMap (internet); offline the map shows the
# stations and zones on a plain background and everything else works.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python}"
PUBLISHED="${ATLAS_PUBLISHED_DIR:-$REPO/artifacts/published}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-4173}"
WORKERS="${ATLAS_API_WORKERS:-2}"
WEB="$REPO/apps/web"

die() { echo "make demo: $*" >&2; exit 1; }

case "$WORKERS" in ''|*[!0-9]*|0) die "ATLAS_API_WORKERS must be a positive integer (got '$WORKERS')";; esac

# 1. published models
[ -f "$PUBLISHED/registry.json" ] || die "no published models at $PUBLISHED (registry.json missing).
  Build them with the documented chain (docs/reproduce.md):  scripts/qa/reproduce.sh          (list the stages)
                                                              scripts/qa/reproduce.sh --run --yes
  or point ATLAS_PUBLISHED_DIR at an existing published directory. A tiny synthetic one for a smoke test:
    make publish-demo-class && ATLAS_PUBLISHED_DIR=artifacts/published-demo-class/published make demo"
n_tasks="$("$PY" -c "import json,sys; print(len(json.load(open(sys.argv[1]))['tasks']))" "$PUBLISHED/registry.json" 2>/dev/null)" \
  || die "$PUBLISHED/registry.json is not valid JSON"
[ "${n_tasks:-0}" -gt 0 ] || die "$PUBLISHED/registry.json lists no tasks"

# 2. built web
command -v node >/dev/null || die "node is required to serve the web (Node 24 was used)"
if [ ! -d "$WEB/node_modules" ]; then
  echo "make demo: installing the web dependencies (npm ci)..."; (cd "$WEB" && npm ci) || die "npm ci failed"
fi
if [ ! -f "$WEB/dist/index.html" ] || [ -n "$(find "$WEB/src" "$WEB/index.html" -newer "$WEB/dist/index.html" -print -quit)" ]; then
  echo "make demo: building the web (npm run build)..."; (cd "$WEB" && npm run build >/dev/null) || die "web build failed (cd apps/web && npm run build)"
fi

# 3. ports
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
port_busy "$API_PORT" && die "port $API_PORT is in use; free it or run API_PORT=<other> make demo"
port_busy "$WEB_PORT" && die "port $WEB_PORT is in use; free it or run WEB_PORT=<other> make demo"

# 4. run both, stop both on Ctrl-C / exit
PIDS=()
cleanup() { trap - EXIT; for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done; wait 2>/dev/null; echo; echo "make demo: stopped."; }
trap cleanup EXIT
trap 'exit 0' INT TERM

cd "$REPO" || exit 1
# EXFUZZY_SRC (contract v0.7): a checkout of the pinned ex_fuzzy commit, for an env that has another one
ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR="$PUBLISHED" PYTHONPATH="${EXFUZZY_SRC:+$EXFUZZY_SRC:}$REPO/src:$REPO/apps/api" \
  "$PY" -m uvicorn atlas_api.main:app --host 127.0.0.1 --port "$API_PORT" --workers "$WORKERS" --log-level warning &
PIDS+=($!)
(cd "$WEB" && ATLAS_API_URL="http://127.0.0.1:$API_PORT" exec node_modules/.bin/vite preview --host 127.0.0.1 --port "$WEB_PORT" --strictPort >/dev/null) &
PIDS+=($!)

for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1 && curl -fs "http://127.0.0.1:$WEB_PORT/" >/dev/null 2>&1; then
    echo "make demo: ExFuzzy Atlas is up ($n_tasks published task(s) from $PUBLISHED; $WORKERS API worker(s))"
    echo "  web  http://127.0.0.1:$WEB_PORT"
    echo "  api  http://127.0.0.1:$API_PORT/docs"
    echo "  Ctrl-C stops both."
    wait -n; echo "make demo: one of the servers exited" >&2; exit 1
  fi
  for p in "${PIDS[@]}"; do kill -0 "$p" 2>/dev/null || die "a server exited during start-up"; done
  sleep 1
done
die "the servers did not answer within 60 s"
