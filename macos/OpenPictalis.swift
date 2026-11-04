// Native macOS window for OpenPictalis: starts the bundled Python server and shows it in a WKWebView.
import AppKit
import WebKit
import UniformTypeIdentifiers

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var log: FileHandle?
    let port = Int(ProcessInfo.processInfo.environment["OPENPICTALIS_PORT"] ?? "") ?? 8788
    var url: URL { URL(string: "http://127.0.0.1:\(port)")! }
    var appRoot: URL { Bundle.main.resourceURL!.appendingPathComponent("app") }
    var home: URL { FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("OpenPictalis") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1360, height: 880), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "OpenPictalis"; window.minSize = NSSize(width: 820, height: 600); window.center(); window.delegate = self
        window.backgroundColor = NSColor(red: 11/255, green: 12/255, blue: 16/255, alpha: 1)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .default()
        web = WKWebView(frame: .zero, configuration: config); web.navigationDelegate = self; web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window.contentView = web; window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<body style='background:#0B0C10;color:#9A9DA8;font:15px ui-monospace,Menlo;display:grid;place-items:center;height:90vh'>Starting OpenPictalis…</body>", baseURL: nil)
        checkServer(attempt: 0)
    }

    func buildMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: "Quit OpenPictalis", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); appItem.submenu = appMenu
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        let viewItem = NSMenuItem(); menu.addItem(viewItem)
        let viewMenu = NSMenu(title: "View"); viewMenu.addItem(withTitle: "Reload", action: #selector(reload(_:)), keyEquivalent: "r"); viewItem.submenu = viewMenu
        NSApp.mainMenu = menu
    }

    func checkServer(attempt: Int) {
        URLSession.shared.dataTask(with: url.appendingPathComponent("api/health")) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if let data = data, let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], json["app"] as? String == "openpictalis" {
                    self.web.load(URLRequest(url: self.url, cachePolicy: .reloadIgnoringLocalCacheData)); return
                }
                if attempt == 0 {
                    if data != nil { self.fail("Another app is using port \(self.port). Quit it and reopen OpenPictalis."); return }
                    do { try self.startServer() } catch { self.fail(error.localizedDescription); return }
                }
                if attempt > 60 { self.fail("The server did not start. See ~/Library/Application Support/OpenPictalis/server.log"); return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.checkServer(attempt: attempt + 1) }
            }
        }.resume()
    }

    func startServer() throws {
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "-u", "-m", "openpictalis"]
        process.currentDirectoryURL = appRoot
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = NSHomeDirectory() + "/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        env["PYTHONPATH"] = appRoot.path
        env["OPENPICTALIS_PORT"] = String(port)
        process.environment = env
        let logURL = home.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        log = try FileHandle(forWritingTo: logURL); process.standardOutput = log; process.standardError = log
        try process.run(); server = process
    }

    func fail(_ text: String) { let alert = NSAlert(); alert.messageText = "OpenPictalis could not start"; alert.informativeText = text; alert.runModal() }
    @objc func reload(_ sender: Any?) { web.reloadFromOrigin() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { if let p = server, p.isRunning { p.terminate() }; try? log?.close() }

    // File pickers, confirms and downloads for the web UI.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedContentTypes = [.png, .jpeg, .webP]
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let target = action.request.url else { decisionHandler(.cancel); return }
        if action.shouldPerformDownload || target.query?.contains("download=1") == true { decisionHandler(.download); return }
        if target.scheme == "about" || (target.host == "127.0.0.1" && target.port == port) { decisionHandler(.allow); return }
        // Model pages and docs open in the default browser.
        if target.scheme == "https" { NSWorkspace.shared.open(target) }
        decisionHandler(.cancel)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let target = action.request.url, target.scheme == "https" { NSWorkspace.shared.open(target) }
        return nil
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
