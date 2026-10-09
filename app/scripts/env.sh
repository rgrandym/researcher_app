# Sourced by dev.sh and build_app.sh: the app's conda env and up-to-date agent CLIs.
#
#   source app/scripts/env.sh            # env ready and active, CLIs checked
#
# The env (default `research_app`, override with CONDA_ENV) holds the backend's packages
# and what the workspace's own scripts import when the app runs them: matplotlib for
# the figures, weasyprint for PDFs. It is created on first use and re-synced whenever
# app/requirements.txt changes.
#
# Claude Code and Codex are updated through the install they came from whenever they
# are older than the latest release. Offline, the check is skipped. Set NO_CLI_UPDATE=1
# to skip it.

ENV_APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV="${CONDA_ENV:-research_app}"
_log() { printf '\033[1;34m[env]\033[0m %s\n' "$*"; }
_warn() { printf '\033[1;33m[env]\033[0m %s\n' "$*" >&2; }

# ------------------------------------------------------------------ conda env

CONDA_BASE="$(conda info --base 2>/dev/null || true)"
if [[ -z "$CONDA_BASE" ]]; then
  for c in /opt/miniconda3 "$HOME/miniconda3" "$HOME/anaconda3" /opt/anaconda3 /opt/homebrew/Caskroom/miniconda/base; do
    [[ -f "$c/etc/profile.d/conda.sh" ]] && CONDA_BASE="$c" && break
  done
fi
[[ -z "$CONDA_BASE" ]] && { _warn "conda not found. Install Miniconda first."; return 1; }
set +u  # conda's activation scripts reference unset variables
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
if ! conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
  _log "Creating conda env '$CONDA_ENV' (Python 3.12)"
  conda create -y -q -n "$CONDA_ENV" python=3.12 >/dev/null
fi
conda activate "$CONDA_ENV"
set -u
STAMP="$CONDA_PREFIX/.research_app_requirements"
if [[ ! -f "$STAMP" || "$ENV_APP_DIR/requirements.txt" -nt "$STAMP" ]]; then
  _log "Installing Python packages into '$CONDA_ENV'"
  python -m pip install -q -r "$ENV_APP_DIR/requirements.txt"
  touch "$STAMP"
fi
_log "Python: $(command -v python) ($(python --version 2>&1))"

# ------------------------------------------------------------------ agent CLIs

# Homebrew's tools (claude, node, pandoc) after the env, so the env's python3 comes first.
export PATH="$CONDA_PREFIX/bin:$PATH:/opt/homebrew/bin:/usr/local/bin"

_version_of() { "$1" --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+)+' | head -1; }
_older_than() { python -c "import sys; v = lambda s: tuple(int(p) for p in s.split('.')); sys.exit(v(sys.argv[1]) >= v(sys.argv[2]))" "$1" "$2"; }

codex_bin() {  # as backend/providers/codex.py: PATH, newest extension copy, the app
  command -v codex && return
  # shellcheck disable=SC2012
  ls -t "$HOME"/.vscode/extensions/openai.chatgpt-*/bin/*/codex \
    "$HOME"/.cursor/extensions/openai.chatgpt-*/bin/*/codex \
    /Applications/Codex.app/Contents/Resources/codex 2>/dev/null | head -1
}

_update_cli() {  # label binary npm-package
  local label="$1" bin="$2" package="$3" real current latest
  [[ -z "$bin" ]] && { _warn "$label not found; set it up under Models."; return 0; }
  current="$(_version_of "$bin")"
  latest="$(npm view "$package" version --fetch-timeout=5000 --fetch-retries=0 2>/dev/null || true)"
  if [[ -z "$current" || -z "$latest" ]]; then
    _warn "Could not check the $label version (offline?); using ${current:-unknown}"
    return 0
  fi
  if ! _older_than "$current" "$latest"; then
    _log "$label: $current (up to date)"
    return 0
  fi
  _log "Updating $label $current -> $latest"
  real="$(python -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$bin")"
  if [[ "$real" == */lib/node_modules/"$package"/* ]]; then
    # Into this copy's own npm prefix, so the copy on PATH is the one that updates.
    npm install -g --silent --prefix "${real%%/lib/node_modules/*}" "$package@latest"
  elif [[ "$real" == */extensions/openai.chatgpt-* ]] && command -v code >/dev/null; then
    code --install-extension openai.chatgpt --force >/dev/null  # the CLI ships with the extension
  elif [[ "$label" == "Claude Code" ]]; then
    "$bin" update
  else
    false
  fi || { _warn "$label could not be updated here; update it by hand"; return 0; }
  _log "$label: $(_version_of "$bin")"
}

if [[ "${NO_CLI_UPDATE:-0}" != 1 ]]; then
  if command -v npm >/dev/null; then
    _update_cli "Claude Code" "$(command -v claude || true)" "@anthropic-ai/claude-code"
    _update_cli "Codex" "$(codex_bin || true)" "@openai/codex"
  else
    _warn "npm not found, so the CLI versions were not checked."
  fi
fi
