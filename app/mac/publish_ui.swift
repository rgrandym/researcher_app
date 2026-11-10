// Publication UI: the only place in the app that can write outside the workspace.
//
// Flow: the page asks (via the `publish` message) to publish proposal X of run Y. This code
// fetches the snapshot itself from the backend it launched, asks the author to pick the
// destination folder, reads the destination itself, shows exactly what would change, and
// requires fresh device-owner authentication. Nothing is remembered: each publication asks again.
// There is no setting, file, environment variable or HTTP call that approves one.

import AppKit
import LocalAuthentication
import WebKit

@MainActor
final class Publisher: NSObject, WKScriptMessageHandlerWithReply {
    weak var webView: WKWebView?
    private var busy = false

    static var auditURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Research/publication-audit.jsonl")
    }

    func userContentController(
        _ controller: WKUserContentController, didReceive message: WKScriptMessage,
        replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void
    ) {
        // Only the app's own main frame, on the page this app loaded, may ask.
        guard message.frameInfo.isMainFrame, let page = webView?.url,
            message.frameInfo.securityOrigin.host == page.host,
            message.frameInfo.securityOrigin.port == (page.port ?? 0),
            message.frameInfo.securityOrigin.protocol == "http",
            page.host == "127.0.0.1" || page.host == "localhost",
            let body = message.body as? [String: Any], let run = body["run"] as? String,
            let proposal = body["proposal"] as? String
        else { return replyHandler(nil, "Publish was refused: not from the app's own page.") }
        guard !busy else { return replyHandler(nil, "A publication is already in progress.") }
        busy = true
        Task {
            defer { busy = false }
            do {
                let text = try await publish(run: run, proposal: proposal, page: page)
                replyHandler(text, nil)
            } catch {
                replyHandler(nil, "\(error)")
            }
        }
    }

    // Every call to the backend carries this launch's token. It is read from the file the
    // launcher wrote, not from the page: the page is given the token in its URL but removes
    // it on load, and a token the page handed back would be the page's claim rather than
    // the launcher's.
    private static func appToken() throws -> String {
        guard let data = try? Data(contentsOf: Config.load().portFile),
            let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let token = info["token"] as? String, !token.isEmpty
        else {
            throw PublishError(
                "This app's token could not be read. Restart the app and try again.")
        }
        return token
    }

    // MARK: flow

    private func publish(run: String, proposal: String, page: URL) async throws -> String {
        let enc = { (s: String) in s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? s }
        var comps = URLComponents(url: page, resolvingAgainstBaseURL: false)!
        comps.path = "/api/runs/\(enc(run))/publications/\(enc(proposal))"
        comps.query = nil
        var fetch = URLRequest(url: comps.url!)
        fetch.setValue(try Self.appToken(), forHTTPHeaderField: "X-App-Token")
        let (data, response) = try await URLSession.shared.data(for: fetch)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard code != 401 else {
            throw PublishError(
                "The backend did not accept this app's token. Restart the app and try again.")
        }
        guard code == 200 else {
            throw PublishError("The proposal is not valid: \(String(data: data, encoding: .utf8) ?? "")")
        }
        let request = try JSONDecoder().decode(PublishRequest.self, from: data)
        try PublishCore.checkRequest(request, now: Int(Date().timeIntervalSince1970))
        if Self.alreadyPublished(request.request_id) { throw PublishError("This request was already published.") }

        // The author, not the proposal, picks the folder; it must be the one the proposal names.
        let proposed = try PublishCore.checkRoot(request.destination_root)
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: proposed)
        panel.message = "Select the destination folder to publish into: \(proposed)"
        panel.prompt = "Select"
        guard panel.runModal() == .OK, let chosen = panel.url else { throw PublishError("Cancelled.") }
        guard chosen.resolvingSymlinksInPath().path == proposed else {
            throw PublishError("You chose \(chosen.path), but the proposal is for \(proposed). Nothing was written.")
        }

        let planned = try PublishCore.plan(request, root: proposed)
        guard review(request, planned, root: proposed) else { throw PublishError("Cancelled. Nothing was written.") }
        try await authenticate(reason: "Publish \(planned.count) file change(s) to \(proposed)")
        // Re-read the destination after the wait: the review must describe what gets written.
        let final = try PublishCore.plan(request, root: proposed)
        guard zip(planned, final).allSatisfy({ $0.oldData == $1.oldData }) else {
            throw PublishError("A target changed while you were reviewing. Nothing was written.")
        }
        guard (try? PublishCore.checkRequest(request, now: Int(Date().timeIntervalSince1970))) != nil else {
            throw PublishError("The request expired. Nothing was written.")
        }
        try audit(["event": "approved", "request": request.request_id, "run": run, "proposal": proposal,
                   "root": proposed, "ops": request.operations.map { ["path": $0.path, "action": $0.action, "sha256": $0.sha256 ?? "", "expect": $0.expect] },
                   "authentication": "deviceOwner"])  // failing here stops before any write
        do {
            try PublishCore.apply(final, root: proposed)
        } catch {
            try? audit(["event": "failed", "request": request.request_id, "error": "\(error)"])
            throw error
        }
        try? audit(["event": "published", "request": request.request_id])
        return "Published \(final.count) change(s) to \(proposed)."
    }

    private func review(_ request: PublishRequest, _ planned: [PlannedOp], root: String) -> Bool {
        var lines = ["Destination: \(root)", "Request: \(request.title)", ""]
        for p in planned {
            let old = p.oldData.flatMap { String(data: $0, encoding: .utf8) }?.components(separatedBy: "\n") ?? []
            let new = p.newData.flatMap { String(data: $0, encoding: .utf8) }?.components(separatedBy: "\n") ?? []
            let diff = new.difference(from: old)
            var added = 0, removed = 0
            var shown: [String] = []
            for change in diff {
                switch change {
                case .insert(_, let line, _): added += 1; if shown.count < 12 { shown.append("   + \(line.prefix(160))") }
                case .remove(_, let line, _): removed += 1; if shown.count < 12 { shown.append("   - \(line.prefix(160))") }
                }
            }
            let kind = p.op.action == "delete" ? "DELETE" : (p.oldData == nil ? "CREATE" : "REPLACE")
            let size = p.newData.map { " \($0.count) bytes" } ?? ""
            lines.append("\(kind)  \(p.op.path)\(size)  (+\(added) / -\(removed) lines)")
            lines += shown
            if added + removed > shown.count { lines.append("   … \(added + removed - shown.count) more changed lines") }
            lines.append("")
        }
        let box = NSAlert()
        box.alertStyle = .warning
        box.messageText = "Publish \(planned.count) change(s) outside the workspace?"
        box.informativeText = "Review the exact changes. You will then be asked to authenticate."
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 760, height: 420))
        let text = NSTextView(frame: scroll.bounds)
        text.isEditable = false
        text.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        text.string = lines.joined(separator: "\n")
        scroll.documentView = text
        scroll.hasVerticalScroller = true
        box.accessoryView = scroll
        box.addButton(withTitle: "Cancel")  // the default button: Return cancels
        box.addButton(withTitle: "Authenticate and publish…")
        return box.runModal() == .alertSecondButtonReturn
    }

    private func authenticate(reason: String) async throws {
        let context = LAContext()
        context.touchIDAuthenticationAllowableReuseDuration = 0  // no reuse of an earlier approval
        var failure: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &failure) else {
            throw PublishError("This Mac cannot authenticate you (\(failure?.localizedDescription ?? "unknown")). Nothing was written.")
        }
        do {
            guard try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)
            else { throw PublishError("Authentication failed.") }
        } catch {
            throw PublishError("Authentication did not succeed. Nothing was written.")
        }
    }

    // MARK: audit (outside the workspace, in the app's own support folder)

    private static func alreadyPublished(_ id: String) -> Bool {
        guard let text = try? String(contentsOf: auditURL, encoding: .utf8) else { return false }
        return text.contains("\"event\":\"approved\"") && text.components(separatedBy: "\n").contains {
            $0.contains("\"request\":\"\(id)\"") && $0.contains("\"event\":\"approved\"")
        }
    }

    private func audit(_ record: [String: Any]) throws {
        var entry = record
        entry["time"] = ISO8601DateFormatter().string(from: Date())
        let data = try JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys])
        let url = Self.auditURL
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let fd = open(url.path, O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw PublishError("Cannot write the audit record. Nothing was written.") }
        defer { close(fd) }
        let line = data + Data("\n".utf8)
        let ok = line.withUnsafeBytes { write(fd, $0.baseAddress, $0.count) == $0.count }
        guard ok, fsync(fd) == 0 else { throw PublishError("Cannot write the audit record. Nothing was written.") }
    }
}
