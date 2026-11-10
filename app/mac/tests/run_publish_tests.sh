#!/usr/bin/env bash
# Builds the publication core with its tests and runs them against temporary folders.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d)"
swiftc -O -swift-version 5 "$HERE/../publish_core.swift" "$HERE/main.swift" -o "$OUT/t"
"$OUT/t"
