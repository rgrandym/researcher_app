#!/usr/bin/env bash
# Scaffold an output folder for a written piece: a CV, a letter, an answer.
#   bash .claude/scripts/new_piece.sh cover-letter "posting-2026" "the author's verbatim prompt"
#
# Kinds: cv · cover-letter · answer · statement · piece
# Prints the run directory path. Safe to re-run: never overwrites prompt.md,
# context.md, or the master document.
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: new_piece.sh <kind> <slug> [verbatim prompt]" >&2; exit 2; }

kind="$1"
case "$kind" in
  cv|cover-letter|answer|statement|piece) ;;
  *) echo "unknown kind: $kind (cv, cover-letter, answer, statement, piece)" >&2; exit 2 ;;
esac

slug=$(printf '%s' "$2" | tr '[:upper:] ' '[:lower:]-' | tr -cd '[:alnum:]-' | cut -c1-50)
[ -n "$slug" ] || { echo "slug is empty after sanitising" >&2; exit 2; }

master="${kind}.md"
dir="outputs/$(date +%F)-${slug}"
mkdir -p "$dir/notes" "$dir/export" "$dir/source_material"
: > "$dir/evidence.jsonl"   # empty is correct: rows appear only if a claim is checked
: > "$dir/blocked.jsonl"

here=$(cd "$(dirname "$0")" && pwd)
python3 - "$dir" "$here" "$kind" "$master" <<'PY'
import sys, datetime
run, here, kind, master = sys.argv[1:5]
sys.path.insert(0, here)
import runmeta
runmeta.write(run, "compose", kind, [master], datetime.date.today().isoformat())
PY

if [ ! -s "$dir/prompt.md" ]; then
  {
    echo "# Request"
    echo
    echo "**Date:** $(date +%F)"
    echo "**Run:** $dir"
    echo "**Kind:** $kind"
    echo
    echo "## Verbatim prompt"
    echo
    if [ $# -ge 3 ]; then printf '%s\n' "$3"; else echo "<paste the author's request here, unedited>"; fi
    echo
    echo "## Clarifications"
    echo
    echo "<questions asked and answers given; assumptions stated if none were asked>"
  } > "$dir/prompt.md"
fi

if [ ! -s "$dir/context.md" ]; then
  {
    echo "# Context — $kind"
    echo
    echo "Filled before the first draft. This is what the piece has to do, and it"
    echo "is the file a later round re-reads instead of guessing."
    echo
    echo "## Reader"
    echo
    echo "<who reads it, what they already know, what they decide afterwards>"
    echo
    echo "## Purpose"
    echo
    echo "<the one thing the reader should do or believe when they finish>"
    echo
    echo "## The line"
    echo
    echo "<the story the piece runs along, in two or three sentences. Every"
    echo " paragraph either advances this or comes out.>"
    echo
    echo "## Constraints"
    echo
    echo "| Constraint | Value |"
    echo "|---|---|"
    echo "| Length | <words or pages> |"
    echo "| Format | <md, docx, pdf> |"
    echo "| Deadline | <date, if any> |"
    echo "| Must include | <named requirements from the brief or the posting> |"
    echo "| Must avoid | <anything the author has ruled out> |"
    echo
    echo "## Source material read"
    echo
    echo "| File | What it gave |"
    echo "|---|---|"
    echo
    echo "## Claims that need checking"
    echo
    echo "<statements the author asserted that no dossier file supports. Listed"
    echo " here, never quietly deleted and never invented around.>"
  } > "$dir/context.md"
fi

if [ ! -s "$dir/source_material/README.md" ]; then
  {
    echo "# Source material for this piece"
    echo
    echo "Everything specific to this one piece: the job posting, the call for"
    echo "proposals, the email thread being answered, the form with its word"
    echo "limits, the author's own draft."
    echo
    echo "Facts about the author come from ../../dossier/ instead. That folder is"
    echo "the standing record and is shared by every piece; this folder is the"
    echo "brief for this one."
    echo
    echo "Nothing here is ever modified or deleted by the pipeline."
  } > "$dir/source_material/README.md"
fi

if [ ! -s "$dir/$master" ]; then
  printf '<!-- %s: written by /compose. Edit this file directly; the next round reads it. -->\n' "$master" > "$dir/$master"
fi

echo "$dir"
