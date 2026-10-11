#!/bin/bash
# Starts the Research app. Research.app (main.swift) runs it with --serve; run it bare for
# the Chrome version, on any system with bash, conda and Chrome.
#
#   start.sh             sync the conda env, update the CLIs, open the app in a Chrome window
#   start.sh --serve     the same, but only start the backend (the Mac app shows the window)
#   start.sh --status    print "turn" (an agent turn is running), "up" or "down"
#   start.sh --stop      stop the backend and close the app window
#   start.sh --window-pid  the open app window's Chrome pid, or nothing
#   start.sh --raise     bring the open window to the front; "raised", or nothing if none
#
# Output goes to app/data/launcher.log.
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
mkdir -p "$APP_DIR/data"
cd "$APP_DIR" || exit 1
PY="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("python3",""))' "$APP_DIR/data/paths.json" 2>/dev/null)"
[[ -x "$PY" ]] || PY=/usr/bin/python3

case "${1:-}" in
  --status|--stop|--window-pid|--raise)
    exec "$PY" "$APP_DIR/mac/launcher.py" "$1"
    ;;
esac

exec >> "$APP_DIR/data/launcher.log" 2>&1
echo "--- $(date)"
echo $$ > "$APP_DIR/data/start.pid"
# shellcheck disable=SC1091
source "$APP_DIR/scripts/env.sh" || { echo "env.sh failed"; exit 1; }
if [[ ! -f "$APP_DIR/web/dist/index.html" ]]; then
  echo "Building the front end"
  (cd "$APP_DIR/web" && { [[ -d node_modules ]] || npm install --no-audit --no-fund; } && npm run build) \
    || { echo "The front end could not be built (needs Node 20+)"; exit 1; }
fi
exec python "$APP_DIR/mac/launcher.py" "$@"
