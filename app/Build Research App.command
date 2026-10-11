#!/bin/bash
# Double-click in Finder to build (or rebuild) Research.app, the macOS Dock app.
# It runs mac/build_app.sh in a Terminal window: syncs the research_app conda env,
# updates Claude Code and Codex, builds the front end, compiles the app and installs it
# (in /Applications if it is already there, else ~/Applications), then opens it.
cd "$(dirname "$0")" || exit 1
bash mac/build_app.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  if [[ -d /Applications/Research.app ]]; then app=/Applications/Research.app; else app="$HOME/Applications/Research.app"; fi
  echo "Research.app is ready in $(dirname "$app"). Opening it: to keep it, right-click its Dock icon > Options > Keep in Dock."
  open "$app"
else
  echo "The build stopped with an error (exit $status). The messages above say why."
fi
echo
read -n 1 -s -r -p "Press any key to close this window."
echo
