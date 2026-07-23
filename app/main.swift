// nathanbot — native macOS app.
// WKWebView shell over the local server. No browser dependency.
// Starts the server itself if it isn't already running.

import Cocoa
import WebKit

let PORT = 7777
let URLSTR = "http://127.0.0.1:\(PORT)"

func serverUp() -> Bool {
    guard let url = URL(string: URLSTR) else { return false }
    var req = URLRequest(url: url)
    req.timeoutInterval = 0.6
    req.httpMethod = "HEAD"
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in
        ok = (resp as? HTTPURLResponse)?.statusCode ?? 0 > 0
        sem.signal()
    }.resume()
    _ = sem.wait(timeout: .now() + 1.0)
    return ok
}

func startServer() {
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    let script = "\(home)/Projects/nathanbot/ui/server.py"
    guard FileManager.default.fileExists(atPath: script) else { return }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    p.arguments = [script]
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    try? p.run()
}

// Transparent strip at the very top. Restores native title-bar behavior over a
// chromeless web view: single drag moves the window, double-click zooms it.
final class DragBar: NSView {
    override var mouseDownCanMoveWindow: Bool { false }   // we handle it ourselves
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 {
            window?.zoom(nil)                              // double-click → expand/restore
        } else {
            window?.performDrag(with: event)              // single drag → move
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!

    // grant the page's getUserMedia (mic) request. The OS-level TCC prompt still
    // gates real access, attributed to this app via NSMicrophoneUsageDescription.
    func webView(_ webView: WKWebView,
                 requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(.grant)
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        if !serverUp() {
            startServer()
            for _ in 0..<25 { if serverUp() { break }; Thread.sleep(forTimeInterval: 0.2) }
        }

        let cfg = WKWebViewConfiguration()
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self                            // enables the mic-permission grant
        web.setValue(false, forKey: "drawsBackground")   // let the page own the background

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1340, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        window.title = "nathanbot"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 720, height: 560)
        // match the drag strip to the app's theme so it isn't a mismatched bar
        window.backgroundColor = NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                ? NSColor(red: 0.031, green: 0.035, blue: 0.043, alpha: 1)  // #08090C
                : NSColor(red: 0.969, green: 0.976, blue: 0.980, alpha: 1)  // #F7F8FA
        }
        window.center()
        window.setFrameAutosaveName("nathanbotMain")
        // green button = native fullscreen; also allows double-click-to-zoom
        window.collectionBehavior.insert(.fullScreenPrimary)

        // Chromeless windows hide the title bar under the web view, so macOS never
        // sees the double-click. A thin transparent drag strip at the very top
        // restores it: drag to move, double-click to zoom — native behavior.
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 1340, height: 900))
        container.autoresizingMask = [.width, .height]
        let barH: CGFloat = 30
        web.frame = NSRect(x: 0, y: 0, width: 1340, height: 900 - barH)
        web.autoresizingMask = [.width, .height]
        let bar = DragBar(frame: NSRect(x: 0, y: 900 - barH, width: 1340, height: barH))
        bar.autoresizingMask = [.width, .minYMargin]   // stays pinned to the top on resize
        container.addSubview(web)
        container.addSubview(bar)
        window.contentView = container
        window.makeKeyAndOrderFront(nil)

        web.load(URLRequest(url: URL(string: URLSTR)!))
        buildMenu()
        NSApp.activate(ignoringOtherApps: true)
    }

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About nathanbot", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        appMenu.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        appMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide nathanbot", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit nathanbot", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        NSApp.mainMenu = main
    }

    @objc func reload() { web.reload() }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
