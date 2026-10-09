#!/bin/bash
# Double-click in Finder to build (or rebuild) ~/Applications/Research.app.
# It runs mac/build_app.sh in a Terminal window: syncs the research_app conda env,
# updates Claude Code and Codex, builds the front end and writes the app bundle.
cd "$(dirname "$0")" || exit 1
bash mac/build_app.sh
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "Research.app is ready in ~/Applications. Opening that folder: drag Research to the Dock."
  open "$HOME/Applications"
else
  echo "The build stopped with an error (exit $status). The messages above say why."
fi
echo
read -n 1 -s -r -p "Press any key to close this window."
echo
