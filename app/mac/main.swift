// Research: the Dock app for the local web app (macOS).
//
// One window showing the app's UI. It attaches to the backend already running for this
// workspace (app/data/app.json), otherwise runs mac/start.sh --serve, which syncs the conda
// env, updates the agent CLIs and starts one. Quitting stops the backend, after asking when
// an agent turn is running. macOS keeps one copy of an app running, so clicking the Dock
// icon brings this window back (un-minimised) instead of opening another. Built by
// build_app.sh, which writes the app folder's path and the PATH of the shell that built it
// into Info.plist.

import AppKit
import WebKit

struct Config {
    let appDir: String
    let path: String

    var startScript: URL { URL(fileURLWithPath: appDir).appendingPathComponent("mac/start.sh") }
    var portFile: URL { URL(fileURLWithPath: appDir).appendingPathComponent("data/app.json") }
    var log: URL { URL(fileURLWithPath: appDir).appendingPathComponent("data/launcher.log") }

    static func load() -> Config {
        let info = Bundle.main.infoDictionary ?? [:]
        return Config(
            appDir: info["ResearchAppDir"] as? String ?? "",
            path: info["ResearchPath"] as? String ?? "/usr/bin:/bin:/usr/sbin:/sbin"
        )
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate,
    WKDownloadDelegate
{
    let config = Config.load()
    var window: NSWindow!
    var webView: WKWebView!
    var starting = false
    var quitting = false
    var downloads: [ObjectIdentifier: URL] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = makeMenu()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()  // keeps the UI's remembered state
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        if #available(macOS 13.3, *) { webView.isInspectable = true }

        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        window = NSWindow(
            contentRect: screen.insetBy(dx: screen.width * 0.05, dy: screen.height * 0.05),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Research"
        window.isReleasedWhenClosed = false  // closing hides it; the Dock icon brings it back
        window.contentView = webView
        window.setFrameAutosaveName("ResearchMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        start()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        showWindow()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    // A running turn is never cut off without asking. Keeping it leaves the backend running
    // on its own; it stops itself once the turn ends, and the next launch attaches to it.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        quitting = true
        let state = run(["--status"])
        if state == "turn" {
            let box = NSAlert()
            box.messageText = "An agent turn is still running"
            box.informativeText = "Stop it, or keep it running in the background?"
            box.addButton(withTitle: "Keep running")
            box.addButton(withTitle: "Stop it")
            box.addButton(withTitle: "Cancel")
            switch box.runModal() {
            case .alertFirstButtonReturn: return .terminateNow
            case .alertSecondButtonReturn: break
            default:
                quitting = false
                return .terminateCancel
            }
        }
        if state != "down" { _ = run(["--stop"]) }
        return .terminateNow
    }

    func showWindow() {
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: backend

    func start() {
        guard !starting, !quitting else { return }
        starting = true
        Task {
            await connect()
            starting = false
        }
    }

    func connect() async {
        if let url = await runningURL() {
            webView.load(URLRequest(url: url))
            return
        }
        status(
            "Starting Research…",
            detail: "It checks the app's Python env and the agent CLIs first, which can take a minute.")
        guard FileManager.default.fileExists(atPath: config.startScript.path) else {
            status(
                "Workspace not found",
                detail: "\(config.appDir) has no mac/start.sh. Rebuild the app with app/mac/build_app.sh.")
            return
        }
        let code = await launch(["--serve"])
        // The backend restarts itself in place to load new code: give it time to answer.
        for _ in 0..<20 {
            if let url = await runningURL() {
                webView.load(URLRequest(url: url))
                return
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        let why = code == 0 ? "The backend did not answer." : "The start stopped with an error."
        status("Research could not start", detail: "\(why) See \(config.log.path).", retry: true)
    }

    // The URL of this workspace's backend, when one is running and answers.
    func runningURL() async -> URL? {
        guard let data = try? Data(contentsOf: config.portFile),
            let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let port = info["port"] as? Int, let token = info["token"] as? String
        else { return nil }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/api/health")!)
        request.timeoutInterval = 1.5
        guard let (body, response) = try? await URLSession.shared.data(for: request),
            (response as? HTTPURLResponse)?.statusCode == 200,
            let health = try? JSONSerialization.jsonObject(with: body) as? [String: Any],
            health["app"] as? String == "research"
        else { return nil }
        var parts = URLComponents(string: "http://127.0.0.1:\(port)/")!
        parts.queryItems = [URLQueryItem(name: "token", value: token)]
        return parts.url
    }

    func process(_ arguments: [String]) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [config.startScript.path] + arguments
        process.currentDirectoryURL = URL(fileURLWithPath: config.appDir)
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = config.path  // apps opened from the Dock get a bare PATH
        process.environment = env
        return process
    }

    // start.sh in the background (its output goes to data/launcher.log); its exit status.
    func launch(_ arguments: [String]) async -> Int32 {
        let process = process(arguments)
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        return await withCheckedContinuation { done in
            process.terminationHandler = { done.resume(returning: $0.terminationStatus) }
            do { try process.run() } catch { done.resume(returning: -1) }
        }
    }

    // A quick start.sh call (--status, --stop); what it printed.
    func run(_ arguments: [String]) -> String {
        let process = process(arguments)
        let out = Pipe()
        process.standardOutput = out
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return "" }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func status(_ title: String, detail: String, retry: Bool = false) {
        let action = retry ? "<p><a href=\"research-app://retry\">Try again</a></p>" : ""
        let html = """
            <html><head><meta charset="utf-8"><style>
            :root { color-scheme: light dark; --fg: #1f2328; --muted: #656d76; --bg: #ffffff; }
            @media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --muted: #8d96a0; --bg: #0d1117; } }
            body { margin: 0; height: 100vh; display: grid; place-items: center; background: var(--bg);
                   color: var(--fg); font: 14px -apple-system, system-ui, sans-serif; text-align: center; }
            p { color: var(--muted); max-width: 32rem; } a { color: inherit; }
            </style></head><body><div><h2>\(title)</h2><p>\(detail)</p>\(action)</div></body></html>
            """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: navigation: app pages here, other sites in the default browser, files to Downloads

    func webView(
        _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if url.scheme == "research-app" {
            start()
            return decisionHandler(.cancel)
        }
        if action.shouldPerformDownload { return decisionHandler(.download) }
        let local = url.host == "localhost" || url.host == "127.0.0.1"
        if !local && ["http", "https", "mailto"].contains(url.scheme ?? "")
            && action.targetFrame?.isMainFrame != false
        {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
        decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void
    ) {
        let disposition = (response.response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition") ?? ""
        let attachment = disposition.lowercased().hasPrefix("attachment")
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        start()  // the backend went away: attach to it again when it is back, or start one
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

    func download(
        _ download: WKDownload, decideDestinationUsing response: URLResponse,
        suggestedFilename: String, completionHandler: @escaping @MainActor (URL?) -> Void
    ) {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let name = (suggestedFilename as NSString)
        var target = folder.appendingPathComponent(suggestedFilename)
        var copy = 1
        while FileManager.default.fileExists(atPath: target.path) {
            copy += 1
            let ext = name.pathExtension.isEmpty ? "" : ".\(name.pathExtension)"
            target = folder.appendingPathComponent("\(name.deletingPathExtension) (\(copy))\(ext)")
        }
        downloads[ObjectIdentifier(download)] = target
        completionHandler(target)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let target = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        // Bounces the Downloads stack in the Dock, as browsers do.
        DistributedNotificationCenter.default().post(
            name: Notification.Name("com.apple.DownloadFileFinished"), object: target.path)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        alert("Download failed", error.localizedDescription)
    }

    // MARK: browser features the UI uses: new tabs, file pickers, confirm dialogs

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for action: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }  // a new tab: the browser
        return nil
    }

    func webView(
        _ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }

    func webView(
        _ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor () -> Void
    ) {
        alert(message, "")
        completionHandler()
    }

    func webView(
        _ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor (Bool) -> Void
    ) {
        let box = NSAlert()
        box.messageText = message
        box.addButton(withTitle: "OK")
        box.addButton(withTitle: "Cancel")
        completionHandler(box.runModal() == .alertFirstButtonReturn)
    }

    func webView(
        _ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
        defaultText: String?, initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor (String?) -> Void
    ) {
        let box = NSAlert()
        box.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        field.stringValue = defaultText ?? ""
        box.accessoryView = field
        box.addButton(withTitle: "OK")
        box.addButton(withTitle: "Cancel")
        completionHandler(box.runModal() == .alertFirstButtonReturn ? field.stringValue : nil)
    }

    func alert(_ title: String, _ text: String) {
        let box = NSAlert()
        box.messageText = title
        box.informativeText = text
        box.runModal()
    }

    // MARK: menu (the Edit menu is what makes copy and paste work in the page)

    @objc func reloadPage() {
        if webView.url?.scheme == "about" { start() } else { webView.reload() }
    }
    @objc func zoomIn() { webView.pageZoom = min(webView.pageZoom + 0.1, 3) }
    @objc func zoomOut() { webView.pageZoom = max(webView.pageZoom - 0.1, 0.5) }
    @objc func zoomReset() { webView.pageZoom = 1 }

    func makeMenu() -> NSMenu {
        let bar = NSMenu()
        func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            let holder = NSMenuItem()
            holder.submenu = menu
            bar.addItem(holder)
            return menu
        }
        func item(
            _ title: String, _ action: Selector?, _ key: String,
            _ mods: NSEvent.ModifierFlags = .command, target: AnyObject? = nil
        ) -> NSMenuItem {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
            entry.keyEquivalentModifierMask = mods
            entry.target = target  // nil: the responder chain (window, web view) handles it
            return entry
        }
        _ = submenu("Research", [
            item("About Research", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
            .separator(),
            item("Hide Research", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:)), ""),
            .separator(),
            item("Quit Research", #selector(NSApplication.terminate(_:)), "q"),
        ])
        _ = submenu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        _ = submenu("View", [
            item("Reload", #selector(reloadPage), "r", target: self),
            .separator(),
            item("Actual Size", #selector(zoomReset), "0", target: self),
            item("Zoom In", #selector(zoomIn), "=", target: self),
            item("Zoom Out", #selector(zoomOut), "-", target: self),
            .separator(),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        NSApp.windowsMenu = submenu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:)), ""),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        return bar
    }
}

let delegate = MainActor.assumeIsolated { AppDelegate() }
NSApplication.shared.delegate = delegate
NSApplication.shared.setActivationPolicy(.regular)
NSApplication.shared.run()
