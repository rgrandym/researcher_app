#!/usr/bin/env bash
# Scaffold an output folder for a research run.
#   bash .claude/scripts/new_run.sh "eu-battery-rules" "the user's verbatim prompt"
# Prints the run directory path. Safe to re-run: never overwrites an existing prompt.md.
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: new_run.sh <slug> [verbatim prompt]" >&2; exit 2; }

slug=$(printf '%s' "$1" | tr '[:upper:] ' '[:lower:]-' | tr -cd '[:alnum:]-' | cut -c1-50)
[ -n "$slug" ] || { echo "slug is empty after sanitising" >&2; exit 2; }

dir="outputs/$(date +%F)-${slug}"
mkdir -p "$dir/notes" "$dir/export" "$dir/figures" "$dir/rounds" \
         "$dir/external_data" "$dir/external_data/ai_reports"
: > "$dir/evidence.jsonl"   # created empty, appended to by scouts
: > "$dir/blocked.jsonl"    # sources nobody could read; see wanted.py

if [ ! -s "$dir/prompt.md" ]; then
  {
    echo "# Request"
    echo
    echo "**Date:** $(date +%F)"
    echo "**Run:** $dir"
    echo
    echo "## Verbatim prompt"
    echo
    if [ $# -ge 2 ]; then printf '%s\n' "$2"; else echo "<paste the user's request here, unedited>"; fi
    echo
    echo "## Clarifications"
    echo
    echo "<questions asked and answers given; assumptions stated if none were asked>"
  } > "$dir/prompt.md"
fi

if [ ! -s "$dir/external_data/README.md" ]; then
  {
    echo "# External data"
    echo
    echo "Drop sources here by hand: datasheets, PDFs, certificates of analysis,"
    echo "purchased reports, spreadsheets, scans, internal memos. Any folder"
    echo "structure is fine; subfolders per vendor or per topic work well."
    echo
    echo "One folder name is reserved. Put AI-generated material in ai_reports/:"
    echo "chatbot research summaries, generated business cases, AI-drafted memos."
    echo "Everything under there is treated as always unverified and is used only"
    echo "as leads, never cited as a source. Everything outside it is treated as a"
    echo "real document from a real source."
    echo
    echo "Agents index this folder by content hash and read only what is new, so"
    echo "adding a file at any point in the run is safe and cheap. Nothing here is"
    echo "ever modified or deleted by the pipeline."
    echo
    echo "    python3 .claude/scripts/external_index.py scan $dir"
    echo
    echo "Say so in chat when you add files, or just ask for the next stage: the"
    echo "scan runs at the start of research, verification, expansion, and edit"
    echo "absorption."
    echo
    echo "## WANTED.md"
    echo
    echo "When the run cannot read a source, it registers the page and the reason"
    echo "and writes WANTED.md in this folder: what is missing, the exact URL that"
    echo "failed, why it failed, and what is already known around it. That is the"
    echo "list to work from. Anything you retrieve goes anywhere under this folder"
    echo "and gets picked up on the next scan."
  } > "$dir/external_data/README.md"
fi

if [ ! -s "$dir/external_data/ai_reports/README.md" ]; then
  {
    echo "# AI-generated material"
    echo
    echo "Anything in this folder is model output and is treated as ALWAYS"
    echo "UNVERIFIED, however well written or well cited it looks."
    echo
    echo "It is used as leads: agents read it for the claims and pointers it"
    echo "contains, write those to a notes file, then source every claim"
    echo "independently from a real document before it can appear in the report."
    echo "Its own citations are leads too, since a reference in a generated"
    echo "report is unverified until somebody fetches it."
    echo
    echo "The indexer refuses to attach evidence rows to files in here. The one"
    echo "exception is a row stating what the document itself claims, which the"
    echo "report attributes to it in the text."
    echo
    echo "Real documents from real sources go anywhere else under external_data/."
  } > "$dir/external_data/ai_reports/README.md"
fi

if [ ! -s "$dir/coverage.md" ]; then
  {
    echo "# Coverage — $dir"
    echo
    echo "Status per row: COVERED · THIN · CONTESTED · GAP · OUT OF SCOPE (with reason)."
    echo "Filled during the gap hunt and the coverage audit; read by /report and /critique."
    echo
    echo "## Sub-questions"
    echo
    echo "| # | Sub-question | Status | Sources | Note |"
    echo "|---|---|---|---|---|"
    echo
    echo "## Dimensions swept"
    echo
    echo "| Dimension | Status | Note |"
    echo "|---|---|---|"
    echo
    echo "## Decisions"
    echo
    echo "<what was excluded, and why>"
  } > "$dir/coverage.md"
fi

echo "$dir"
