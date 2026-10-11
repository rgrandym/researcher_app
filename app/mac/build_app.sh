#!/usr/bin/env bash
# Build Research.app, the macOS Dock app (in /Applications if it is already there, else
# ~/Applications). Other systems, or Chrome on a Mac: bash app/mac/start.sh.
#
#   bash app/mac/build_app.sh
#
# 1. Activates the app's conda env (scripts/env.sh: creates it, installs the packages,
#    updates the agent CLIs), then resolves python, claude, node, code and pandoc and
#    writes their absolute paths to app/data/paths.json: an app started from the Dock does not get the shell's
#    PATH. Codex is found by the backend at each start instead, because its folder moves
#    with every VS Code extension update.
# 2. Builds the front end.
# 3. Compiles the app (mac/main.swift: a native window on the app's UI, which runs
#    mac/start.sh --serve for the backend) and its icon (mac/make_icon.swift, turned into
#    an .icns by sips and iconutil), and signs it. A compiled app can ask macOS for access
#    to the Desktop folder where this workspace lives, and the processes it starts share
#    that access. Needs the Xcode command line tools (swiftc).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Rebuild in place wherever Research.app already is (so a Dock item keeps working);
# otherwise ~/Applications.
if [[ -z "${DEST:-}" ]]; then
  if [[ -d /Applications/Research.app ]]; then DEST=/Applications; else DEST="$HOME/Applications"; fi
fi
BUNDLE="$DEST/Research.app"
log() { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[build]\033[0m %s\n' "$*" >&2; }

[[ "$(uname)" == Darwin ]] || { warn "Research.app is for macOS. Use: bash app/mac/start.sh"; exit 1; }
command -v swiftc >/dev/null || { warn "swiftc not found. Run: xcode-select --install"; exit 1; }

# ------------------------------------------------------------------ 1. binaries
mkdir -p "$APP_DIR/data"
# The app's conda env, created or synced, with Claude Code and Codex updated.
# shellcheck disable=SC1091
source "$APP_DIR/scripts/env.sh"
missing=()
resolve() { command -v "$1" 2>/dev/null || true; }
PY="$(resolve python)"; CLAUDE="$(resolve claude)"; NODE="$(resolve node)"; CODE="$(resolve code)"; PANDOC="$(resolve pandoc)"
[[ -z "$PY" ]] && { warn "python3 not found"; exit 1; }
for pair in "claude:$CLAUDE" "node:$NODE" "code:$CODE" "pandoc:$PANDOC"; do
  [[ -z "${pair#*:}" ]] && missing+=("${pair%%:*}")
done
"$PY" - "$APP_DIR/data/paths.json" "$PY" "$CLAUDE" "$NODE" "$CODE" "$PANDOC" <<'EOF'
import json, sys
out, py, claude, node, code, pandoc = sys.argv[1:]
paths = {k: v for k, v in {"python3": py, "claude": claude, "node": node, "code": code, "pandoc": pandoc}.items() if v}
open(out, "w").write(json.dumps(paths, indent=2) + "\n")
EOF
log "Paths written to app/data/paths.json (python3: $PY)"
if ((${#missing[@]})); then warn "Not found on PATH: ${missing[*]}. Those features will be unavailable."; fi
"$PY" -c "import fastapi, uvicorn, pydantic" 2>/dev/null || { warn "This Python lacks fastapi/uvicorn/pydantic: $PY -m pip install fastapi uvicorn pydantic"; exit 1; }

# ------------------------------------------------------------------ 2. front end
command -v npm >/dev/null || { warn "npm not found"; exit 1; }
log "Building the front end"
(cd "$APP_DIR/web" && { [[ -d node_modules ]] || npm install --no-audit --no-fund; } && npm run build >/dev/null)

# ------------------------------------------------------------------ 3. the bundle
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
APP="$WORK/Research.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

xml() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }
# The Dock starts apps with a bare PATH; keep the builder's, plus the usual install places.
LAUNCH_PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cat > "$WORK/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Research</string>
  <key>CFBundleDisplayName</key><string>Research</string>
  <key>CFBundleIdentifier</key><string>local.research.launcher</string>
  <key>CFBundleExecutable</key><string>Research</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSDesktopFolderUsageDescription</key><string>Research runs your research workspace, which is in your Desktop folder.</string>
  <key>NSDocumentsFolderUsageDescription</key><string>Research opens files in your research workspace.</string>
  <key>ResearchAppDir</key><string>$(xml "$APP_DIR")</string>
  <key>ResearchPath</key><string>$(xml "$LAUNCH_PATH")</string>
</dict>
</plist>
PLIST
plutil -lint "$WORK/Info.plist" >/dev/null

# macOS keeps a permission (Desktop folder access) only while the app's code
# identity holds. Two things keep it from changing: an app whose contents did not change
# is left exactly as it is, and the app is signed with a stable local certificate, so a
# rebuilt app keeps its identity too. (An ad-hoc signature is a hash of the files: every
# rebuild was a new app to macOS, which asked for its permissions again.)
BUILD_FORMAT=3
STAMP="$( { echo "$BUILD_FORMAT"; swiftc --version 2>&1
  cat "$WORK/Info.plist" "$APP_DIR/mac/main.swift" "$APP_DIR/mac/make_icon.swift"; } | shasum -a 256 | cut -d' ' -f1)"
SIGNER="Research Local Signing"
if [[ -d "$BUNDLE" && "$(cat "$BUNDLE/Contents/Resources/build-stamp" 2>/dev/null)" == "$STAMP" ]] \
  && codesign -dr - "$BUNDLE" 2>&1 | grep -q "certificate leaf" \
  && codesign --verify --deep --strict "$BUNDLE" 2>/dev/null; then
  log "Research.app is unchanged: left as it is, so macOS keeps its permissions."
  exit 0
fi

ensure_signer() {
  security find-identity -p codesigning 2>/dev/null | grep -q "\"$SIGNER\"" && return 0
  log "Creating the local signing certificate \"$SIGNER\" (once; it stays in your login keychain)"
  local d ok
  d="$(mktemp -d)"
  printf '%s\n' '[req]' 'distinguished_name = dn' 'prompt = no' 'x509_extensions = ext' '[dn]' \
    "CN = $SIGNER" '[ext]' 'basicConstraints = critical,CA:false' \
    'keyUsage = critical,digitalSignature' 'extendedKeyUsage = critical,codeSigning' > "$d/cert.cnf"
  /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -keyout "$d/key.pem" -out "$d/cert.pem" \
    -days 3650 -config "$d/cert.cnf" >/dev/null 2>&1 \
    && /usr/bin/openssl pkcs12 -export -inkey "$d/key.pem" -in "$d/cert.pem" -out "$d/id.p12" \
      -passout pass:research -name "$SIGNER" >/dev/null 2>&1 \
    && security import "$d/id.p12" -k "$HOME/Library/Keychains/login.keychain-db" -P research \
      -T /usr/bin/codesign >/dev/null 2>&1
  ok=$?
  rm -rf "$d"
  return $ok
}

log "Compiling"
swiftc -O -swift-version 5 "$APP_DIR/mac/main.swift" -o "$APP/Contents/MacOS/Research"
swiftc -O "$APP_DIR/mac/make_icon.swift" -o "$WORK/make_icon"
"$WORK/make_icon" "$WORK/icon.png"
ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$WORK/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$WORK/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
cp "$WORK/Info.plist" "$APP/Contents/Info.plist"
echo "$STAMP" > "$APP/Contents/Resources/build-stamp"
if ensure_signer && codesign --force -s "$SIGNER" "$APP" 2>/dev/null; then
  signed="Signed with \"$SIGNER\": permissions you grant survive later rebuilds."
else
  warn "The local certificate could not be used; signed ad hoc, so macOS may ask for permissions again after a rebuild."
  codesign --force -s - "$APP" 2>/dev/null || warn "Could not sign the app"
fi

if pgrep -xq Research || pgrep -f -q "$BUNDLE/Contents/MacOS/applet"; then
  warn "Research is running: quit it and open it again to use this build."
fi
if [[ -e "$BUNDLE" ]]; then
  existing="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$BUNDLE/Contents/Info.plist" 2>/dev/null || true)"
  [[ "$existing" == local.research.launcher ]] || { warn "$BUNDLE exists and is not this app; left alone"; exit 1; }
  rm -rf "$BUNDLE"
fi
mkdir -p "$DEST"
mv "$APP" "$BUNDLE"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$BUNDLE" >/dev/null 2>&1 || true
[[ -n "${signed:-}" ]] && log "$signed"

log "Done: $BUNDLE"
log "The first time it opens, macOS asks whether Research may access your Desktop folder."
log "Click OK: the workspace lives there. Then right-click its Dock icon > Options > Keep in Dock."
