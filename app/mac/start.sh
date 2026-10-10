#!/bin/bash
# What Research.app runs (the Dock app is a thin AppleScript shell around this file).
#
#   start.sh             sync the conda env, update the CLIs, run the launcher
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
exec python "$APP_DIR/mac/launcher.py"
