// Tests for the publication core, run against temporary folders only.
// Build and run: bash app/mac/tests/run_publish_tests.sh
// This file is not part of the app target and contains no approval path: it calls the core
// directly, the way the app does after the author has approved.
import Foundation

var failures = 0
func check(_ ok: Bool, _ what: String) { if !ok { failures += 1; print("FAIL  \(what)") } else { print("ok    \(what)") } }
func b64(_ s: String) -> String { Data(s.utf8).base64EncodedString() }
func op(_ path: String, _ action: String = "write", expect: String = "absent", text: String = "new\n") -> PublishOp {
    let data = Data(text.utf8)
    return PublishOp(path: path, action: action, expect: expect,
                     sha256: action == "write" ? sha256Hex(data) : nil, content: action == "write" ? data.base64EncodedString() : nil)
}
func request(_ ops: [PublishOp], expires: Int = Int(Date().timeIntervalSince1970) + 600) -> PublishRequest {
    PublishRequest(version: 1, run: "r", proposal: "p", title: "t", destination_root: "/x", operations: ops,
                   issued: 0, expires: expires, request_id: "id")
}
func fails(_ body: () throws -> Void) -> Bool { do { try body(); return false } catch { return true } }

let fm = FileManager.default
let base = fm.temporaryDirectory.appendingPathComponent("publish-test-\(UUID().uuidString)")
try fm.createDirectory(at: base.appendingPathComponent("a/b/docs"), withIntermediateDirectories: true)
let root = base.appendingPathComponent("a/b").resolvingSymlinksInPath().path
let docs = root + "/docs"
func put(_ name: String, _ text: String) { fm.createFile(atPath: docs + "/" + name, contents: Data(text.utf8)) }
func get(_ name: String) -> String? { try? String(contentsOfFile: docs + "/" + name, encoding: .utf8) }
let old = sha256Hex(Data("old\n".utf8))

// static checks
let now = Int(Date().timeIntervalSince1970)
for bad in ["../x", "/abs", "a//b", "a/./b", "a\\b", "a/\u{1}b", ""] {
    check(fails { try PublishCore.checkRequest(request([op(bad)]), now: now) }, "refuses path \(bad.debugDescription)")
}
check(fails { try PublishCore.checkRequest(request([op("d/A.md"), op("d/a.md")]), now: now) }, "refuses duplicate targets")
check(fails { try PublishCore.checkRequest(request([op("d/A.md")], expires: now - 1), now: now) }, "refuses an expired request")
check(fails { try PublishCore.checkRequest(request((0..<33).map { op("d/\($0).md") }), now: now) }, "refuses more than 32 operations")
let tampered = PublishOp(path: "docs/A.md", action: "write", expect: "absent", sha256: sha256Hex(Data("other".utf8)), content: b64("new"))
check(fails { try PublishCore.checkRequest(request([tampered]), now: now) }, "refuses content that does not match its hash")
check(fails { _ = try PublishCore.checkRoot("/") }, "refuses root /")
check(fails { _ = try PublishCore.checkRoot(NSHomeDirectory()) }, "refuses the home folder")

// create, replace, delete
put("old.md", "old\n")
put("gone.md", "old\n")
let r1 = request([op("docs/new.md"), op("docs/old.md", expect: old, text: "replaced\n"), op("docs/gone.md", "delete", expect: old)])
do {
    let planned = try PublishCore.plan(r1, root: root)
    try PublishCore.apply(planned, root: root)
    check(get("new.md") == "new\n" && get("old.md") == "replaced\n" && get("gone.md") == nil, "creates, replaces and deletes")
    check(try fm.contentsOfDirectory(atPath: docs).allSatisfy { !$0.hasPrefix(".publish-") }, "leaves no staged files")
} catch { check(false, "apply: \(error)") }

// preconditions
put("p.md", "old\n")
check(fails { _ = try PublishCore.plan(request([op("docs/p.md")]), root: root) }, "refuses to clobber an existing file")
check(fails { _ = try PublishCore.plan(request([op("docs/p.md", expect: sha256Hex(Data("zzz".utf8)))]), root: root) }, "refuses a changed file")
check(fails { _ = try PublishCore.plan(request([op("docs/missing.md", expect: old)]), root: root) }, "refuses a missing file that was expected")
check(fails { _ = try PublishCore.plan(request([op("nodir/x.md")]), root: root) }, "refuses a missing parent folder")

// symlinks, hard links, special files
try fm.createSymbolicLink(atPath: docs + "/link.md", withDestinationPath: docs + "/p.md")
check(fails { _ = try PublishCore.plan(request([op("docs/link.md", expect: old)]), root: root) }, "refuses a symlink target")
try fm.createSymbolicLink(atPath: root + "/linkdir", withDestinationPath: docs)
check(fails { _ = try PublishCore.plan(request([op("linkdir/q.md")]), root: root) }, "refuses a symlinked parent")
try fm.linkItem(atPath: docs + "/p.md", toPath: docs + "/hard.md")
check(fails { _ = try PublishCore.plan(request([op("docs/hard.md", expect: old)]), root: root) }, "refuses a hard-linked file")
mkfifo(docs + "/fifo", 0o644)
check(fails { _ = try PublishCore.plan(request([op("docs/fifo", expect: old)]), root: root) }, "refuses a special file")

// a change between plan and apply, and rollback
put("r1.md", "old\n"); put("r2.md", "old\n")
let r2 = request([op("docs/r1.md", expect: old, text: "A\n"), op("docs/r2.md", expect: old, text: "B\n")])
do {
    let planned = try PublishCore.plan(r2, root: root)
    put("r2.md", "someone else\n")  // changes after the plan
    check(fails { try PublishCore.apply(planned, root: root) }, "refuses when a target changed after review")
    check(get("r1.md") == "old\n" && get("r2.md") == "someone else\n", "rolls back the first change")
} catch { check(false, "rollback setup: \(error)") }
try? fm.removeItem(at: base)
print(failures == 0 ? "ALL PASSED" : "\(failures) FAILED")
exit(failures == 0 ? 0 : 1)
