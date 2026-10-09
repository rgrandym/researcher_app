#!/usr/bin/env bash
# Run the Research app for development: backend on :8765 with reload, Vite on :5174.
#
#   bash app/scripts/dev.sh              # start both and open the app window
#   bash app/scripts/dev.sh --stop       # stop both and exit
#   bash app/scripts/dev.sh --no-update  # skip the Claude Code / Codex version check
#
# Runs in the app's conda env (scripts/env.sh creates and syncs it) and updates the
# agent CLIs first. The app opens as a Chrome app window. Closing it shuts down both
# servers about 15 seconds later; if an agent turn is still running, you are asked
# first. Ctrl-C also stops both.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8765}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
RUN_DIR="$APP_DIR/data/dev"
IDLE_S="${IDLE_S:-15}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
log() { printf '\033[1;34m[dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dev]\033[0m %s\n' "$*" >&2; }

for arg in "$@"; do
  case "$arg" in
    --stop|--no-update) ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

free_port() {
  local pids
  pids="$(lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  log "Stopping what listens on port $1"
  kill $pids 2>/dev/null || true
  for _ in {1..20}; do lsof -ti tcp:"$1" -sTCP:LISTEN >/dev/null 2>&1 || return 0; sleep 0.25; done
  lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
}

free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"
[[ " $* " == *" --stop "* ]] && { log "Stopped."; exit 0; }
[[ " $* " == *" --no-update "* ]] && export NO_CLI_UPDATE=1

# shellcheck disable=SC1091
source "$APP_DIR/scripts/env.sh"
PY="$(command -v python)"

command -v npm >/dev/null || { warn "npm not found. Install Node.js 20+ (brew install node)."; exit 1; }
if [[ ! -d "$APP_DIR/web/node_modules" || "$APP_DIR/web/package.json" -nt "$APP_DIR/web/node_modules" ]]; then
  log "Installing npm dependencies"
  (cd "$APP_DIR/web" && npm install --no-audit --no-fund --silent)
fi

mkdir -p "$RUN_DIR"
TOKEN="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(24))')"

log "Backend  -> http://127.0.0.1:$BACKEND_PORT"
(cd "$APP_DIR" && RESEARCH_APP_TOKEN="$TOKEN" exec "$PY" -m uvicorn backend.main:app --reload --reload-dir backend \
  --host 127.0.0.1 --port "$BACKEND_PORT") >"$RUN_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
log "Frontend -> http://127.0.0.1:$FRONTEND_PORT"
(cd "$APP_DIR/web" && BACKEND_PORT="$BACKEND_PORT" FRONTEND_PORT="$FRONTEND_PORT" VITE_APP_TOKEN="$TOKEN" \
  exec npx vite --port "$FRONTEND_PORT" --strictPort) >"$RUN_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
CHROME_PID=""
TAIL_PIDS=""

cleanup() {
  trap - INT TERM EXIT
  echo
  log "Shutting down the backend and the front end"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  [[ -n "$TAIL_PIDS" ]] && { pkill -P $$ tail 2>/dev/null; kill $TAIL_PIDS 2>/dev/null; } || true
  [[ -n "$CHROME_PID" ]] && kill "$CHROME_PID" 2>/dev/null || true
  free_port "$BACKEND_PORT"
  free_port "$FRONTEND_PORT"
  log "Stopped."
}
trap cleanup INT TERM EXIT

for _ in {1..80}; do curl -fs -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" && break; sleep 0.25; done
curl -fs -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" || { warn "Backend did not start:"; tail -n 20 "$RUN_DIR/backend.log"; exit 1; }
for _ in {1..80}; do curl -fs -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/" && break; sleep 0.25; done

URL="http://127.0.0.1:$FRONTEND_PORT"
if [[ "${OPEN_BROWSER:-1}" == 1 ]]; then
  if [[ -x "$CHROME" ]]; then
    # Its own profile: a separate Chrome instance this script can close, your usual
    # Chrome left alone.
    "$CHROME" --app="$URL" --user-data-dir="$APP_DIR/data/chrome-dev" --no-first-run \
      --no-default-browser-check --window-size=1400,900 >/dev/null 2>&1 &
    CHROME_PID=$!
  else
    open "$URL"
  fi
fi
log "App: $URL   (logs in app/data/dev/; close the window or press Ctrl-C to stop)"

# The watcher's own health polls are left out of the stream.
tail -n 0 -F "$RUN_DIR/backend.log" | grep --line-buffered -v '/api/health' | sed -u 's/^/[api] /' &
TAIL_PIDS="$!"
disown
tail -n 0 -F "$RUN_DIR/frontend.log" | sed -u 's/^/[web] /' &
TAIL_PIDS="$TAIL_PIDS $!"
disown

# Watch the open windows (the backend counts their live connections). Once one has
# connected and none has been open for IDLE_S seconds, stop everything.
health() { curl -fs --max-time 2 "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null || true; }
field() { "$PY" -c "import json, sys; d = json.loads(sys.stdin.read() or '{}'); print(d.get('$1', ''))"; }
ask_keep() {
  osascript -e 'display dialog "An agent turn is still running. Keep the app running, or stop it?" buttons {"Stop it", "Keep running"} default button "Keep running" with title "Research"' 2>/dev/null | grep -q "Keep running"
}
seen=0; idle_since=0
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 2
  h="$(health)"
  [[ -z "$h" ]] && continue  # reloading
  clients="$(printf '%s' "$h" | field clients)"
  if [[ "${clients:-0}" -gt 0 ]]; then seen=1; idle_since=0; continue; fi
  [[ "$seen" == 0 ]] && continue
  [[ "$idle_since" == 0 ]] && idle_since=$(date +%s)
  (( $(date +%s) - idle_since < IDLE_S )) && continue
  if [[ "$(printf '%s' "$h" | field running)" == "True" ]] && ask_keep; then
    log "Keeping the app running. Reopen $URL, or press Ctrl-C to stop."
    seen=0; idle_since=0
    continue
  fi
  log "The app window was closed."
  exit 0
done
warn "A server exited. See the logs above."
