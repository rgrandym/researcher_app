// Bring one process's windows in front of every other app, as a Dock click would:
//   osascript -l JavaScript app/mac/raise.js <pid>
// Activation only. A reopen Apple event is never sent: Chrome answers one by opening a new
// window. Un-minimising is done by the Dock app itself (build_app.sh), through System Events,
// before this runs. Addressed by pid, so the author's own Chrome is untouched.
ObjC.import('AppKit')

function run(argv) {
  const pid = parseInt(argv[0], 10)
  const app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(pid)
  if (app.isNil()) return 'gone'
  // NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps; un-hides too.
  return app.activateWithOptions(3) ? 'raised' : 'refused'
}
