import AppKit
import WebKit
import UniformTypeIdentifiers
import SwiftUI

private let workspaceURL = URL(string: "http://127.0.0.1:8766/workspace/#desk")!

private func isWorkspaceURL(_ url: URL?) -> Bool {
    guard let url = url else { return false }
    return url.scheme == "http" && url.host == "127.0.0.1" && url.port == 8766
        && url.user == nil && url.password == nil
}

private func isExportURL(_ url: URL?) -> Bool {
    guard isWorkspaceURL(url), let path = url?.path else { return false }
    return ["/api/template", "/api/export/drafts", "/api/planning/export",
            "/api/operations/package", "/api/operations/backup"].contains(path)
}

private final class DownloadSave {
    let download: WKDownload
    var destination: URL?
    var staging: URL?
    var stagingDirectory: URL?
    var existingAttributes: [FileAttributeKey: Any]?
    init(_ download: WKDownload) { self.download = download }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
    WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var nativeWorkspace: NSView?
    private var nativeStore: NativeWorkspaceStore?
    private var publishingReturnsToNative = false
    private var selectingFiles = false
    private var downloads: [ObjectIdentifier: DownloadSave] = [:]
    private var publishingWorkspace: AnyObject?
    private var rednoteUploadCoordinator: AnyObject?
    private var publishingQueueCoordinator: AnyObject?
    private var metricsReaderCoordinator: AnyObject?
    private var statusItem: NSStatusItem?
    private var openingPublishing = false
    private var openingUploadFallback = false
    private var terminatingSessionVault = false
    private var startupAttempt: UUID?
    private var showingStartupPage = false
    private var startupProcess: Process?
    private var authorizedProjectURL: URL?
    private var projectScopeStarted = false
    private var choosingProject = false
    private let projectBookmarkKey = "MediaDeskWorkspaceBookmark"
    private let exportFileQueue = DispatchQueue(label: "local.spt.studio.export-files", qos: .utility)

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenus()
        installStatusItem()

        let userContentController = WKUserContentController()
        userContentController.add(self, name: "chooseMedia")
        userContentController.add(self, name: "openPublishing")
        userContentController.add(self, name: "chooseWorkspace")
        userContentController.add(self, name: "startRednoteUpload")
        userContentController.add(self, name: "cancelRednoteUpload")
        userContentController.add(self, name: "previewRednoteUpload")
        userContentController.add(self, name: "runPublishingQueue")
        userContentController.add(self, name: "previewPublishingQueue")
        userContentController.addUserScript(WKUserScript(
            source: "window.mediaNativeAvailable = true; window.mediaPublishingNativeAvailable = true; window.mediaRednoteUploadNativeAvailable = true; window.mediaPublishingQueueNativeAvailable = true; window.mediaMetricsReaderAvailable = true;",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: false   // the publishing tools run in a same-origin frame inside the SPT page
        ))

        let configuration = WKWebViewConfiguration()
        configuration.userContentController = userContentController
        configuration.websiteDataStore = .nonPersistent()
        configuration.mediaTypesRequiringUserActionForPlayback = [.audio, .video]
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false

        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsLinkPreview = false

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "SPT"
        window.minSize = NSSize(width: 820, height: 600)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startWorkspace()
        // Only persisted, explicitly enqueued tasks can be claimed. Starting
        // the worker never creates a draft or authorizes a publication.
        if #available(macOS 14.0, *) { queueCoordinator().start() }
        // SPT 读数据: claims read requests from the local server and reads 小红书
        // with the accounts' own saved sessions (MetricsReader.swift).
        if #available(macOS 14.0, *) {
            let reader = MetricsReaderCoordinator()
            reader.start()
            metricsReaderCoordinator = reader
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard #available(macOS 14.0, *) else { return .terminateNow }
        guard !terminatingSessionVault else { return .terminateLater }
        terminatingSessionVault = true
        RednoteSessionVault.shared.flushForTermination { [weak self] success in
            DispatchQueue.main.async {
                guard let self = self else { sender.reply(toApplicationShouldTerminate: true); return }
                if !success {
                    self.terminatingSessionVault = false
                    let alert = NSAlert()
                    alert.messageText = "这次会话未能保存"
                    alert.informativeText = "可返回处理系统钥匙串提示。仍然退出后，下次可能需要重新登录。"
                    alert.addButton(withTitle: "返回处理")
                    alert.addButton(withTitle: "仍然退出")
                    let proceed = alert.runModal() == .alertSecondButtonReturn
                    sender.reply(toApplicationShouldTerminate: proceed)
                    return
                }
                sender.reply(toApplicationShouldTerminate: success)
            }
        }
        return .terminateLater
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window?.makeKeyAndOrderFront(nil)
        return true
    }

    private func installMenus() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "SPT")
        appMenu.addItem(withTitle: "关于 SPT", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏 SPT", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 SPT", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)

        let viewItem = NSMenuItem()
        let viewMenu = NSMenu(title: "显示")
        let home = viewMenu.addItem(withTitle: "回到 SPT 首页", action: #selector(returnToNativeWorkspace), keyEquivalent: "0")
        home.target = self
        let reload = viewMenu.addItem(withTitle: "重新载入工作台", action: #selector(reloadWorkspace), keyEquivalent: "r")
        reload.target = self
        viewItem.submenu = viewMenu
        menu.addItem(viewItem)
        NSApp.mainMenu = menu
    }

    @objc private func reloadWorkspace() {
        if #available(macOS 14.0, *), let pane = publishingWorkspace as? PublishingWorkspace,
           window.contentView === pane.view {
            pane.refresh()
        } else if window.contentView === nativeWorkspace {
            if let store = nativeStore { Task { await store.reload() } }
        } else if showingStartupPage { startWorkspace() }
        else if window.contentView === webView { webView.reload() }
    }

    @objc private func returnToNativeWorkspace() {
        showNativeWorkspace()
    }

    private func showNativeWorkspace() {
        // SPT's interface is the local web page; the SwiftUI workspace views are no longer shown.
        window.contentView = webView
        window.title = "SPT"
        let onWorkspace = isWorkspaceURL(webView.url) && (webView.url?.path.hasPrefix("/workspace") ?? false)
        if !onWorkspace { webView.load(URLRequest(url: workspaceURL)) }
        window.makeKeyAndOrderFront(nil)
    }

    private func openLegacyTool(_ route: String) {
        let allowed = ["accounts", "studio", "publish", "planner", "uploads",
                       "data", "desk", "connections", "planning", "overview"]
        guard allowed.contains(route),
              let destination = URL(string: "http://127.0.0.1:8766/legacy/#" + route)
        else { return }
        window.contentView = webView
        webView.load(URLRequest(url: destination))
    }

    private func installStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "SPT"
        item.button?.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        let menu = NSMenu()
        let open = menu.addItem(withTitle: "打开 SPT", action: #selector(showMainWindow), keyEquivalent: "")
        open.target = self
        menu.addItem(.separator())
        let quit = menu.addItem(withTitle: "退出", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "")
        quit.target = NSApp
        item.menu = menu
        statusItem = item
    }

    @objc private func showMainWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func isProjectFolder(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.appendingPathComponent("启动.py").path)
    }

    /// The SPT folder this app belongs to: the app sits at the folder's top level or in native/build/.
    /// nil when the app was moved elsewhere (e.g. /Applications); the user then picks the folder once.
    private func projectRootURL() -> URL? {
        if let path = Bundle.main.object(forInfoDictionaryKey: "MediaDeskWorkspaceRoot") as? String,
           path.hasPrefix("/"), isProjectFolder(URL(fileURLWithPath: path, isDirectory: true)) {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        let parent = Bundle.main.bundleURL.resolvingSymlinksInPath().deletingLastPathComponent()
        if isProjectFolder(parent) { return parent }
        let build = parent.deletingLastPathComponent().deletingLastPathComponent()
        return isProjectFolder(build) ? build : nil
    }

    private func acceptsProject(_ url: URL) -> Bool {
        guard isProjectFolder(url) else { return false }
        guard let expected = projectRootURL() else { return true }
        return url.standardizedFileURL.path == expected.standardizedFileURL.path
    }

    private func startWorkspace() {
        // A healthy local service is sufficient. Never reopen a Desktop script
        // merely to display the UI: macOS may be waiting for file access consent.
        let destination = isWorkspaceURL(webView.url) ? webView.url! : workspaceURL
        let attempt = UUID()
        startupAttempt = attempt
        showStartupPage(title: "正在启动 SPT…", detail: "", actions: false)
        checkWorkspaceHealth { [weak self] healthy in
            guard let self = self, self.startupAttempt == attempt else { return }
            if healthy { self.finishWorkspaceStartup(attempt, destination: destination); return }
            guard self.restoreProjectAccess() else {
                self.startupAttempt = nil
                self.showStartupPage(title: "打开 SPT 文件夹", detail: "第一次打开，请选择 SPT 文件夹（里面有 启动.py、工作区），允许软件读取你的资料。", actions: true)
                return
            }
            if let process = self.startupProcess, process.isRunning {
                self.pollWorkspaceStartup(attempt, destination: destination, deadline: Date().addingTimeInterval(10))
                return
            }
            self.launchWorkspace(attempt, destination: destination)
        }
    }

    private func restoreProjectAccess() -> Bool {
        if authorizedProjectURL != nil { return true }
        guard let data = UserDefaults.standard.data(forKey: projectBookmarkKey) else { return false }
        do {
            var stale = false
            let project = try URL(resolvingBookmarkData: data, options: [.withSecurityScope, .withoutUI],
                                  relativeTo: nil, bookmarkDataIsStale: &stale)
            guard acceptsProject(project) else { return false }
            projectScopeStarted = project.startAccessingSecurityScopedResource()
            authorizedProjectURL = project
            if stale {
                let refreshed = try project.bookmarkData(options: .withSecurityScope,
                                                        includingResourceValuesForKeys: nil, relativeTo: nil)
                UserDefaults.standard.set(refreshed, forKey: projectBookmarkKey)
            }
            return true
        } catch {
            if projectScopeStarted { authorizedProjectURL?.stopAccessingSecurityScopedResource() }
            projectScopeStarted = false
            authorizedProjectURL = nil
            return false
        }
    }

    @objc private func chooseProjectFolder() {
        guard !choosingProject else { return }
        choosingProject = true
        startupAttempt = nil
        let expected = projectRootURL()?.standardizedFileURL
        let panel = NSOpenPanel()
        panel.title = "打开 SPT 文件夹"
        panel.message = "选择 SPT 文件夹（里面有 启动.py、工作区），允许软件读取你的资料。"
        panel.prompt = "打开项目"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        panel.directoryURL = expected
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            self.choosingProject = false
            guard response == .OK, let project = panel.url else { return }
            guard self.acceptsProject(project) else {
                self.showStartupPage(title: "请选择 SPT 文件夹",
                                     detail: expected?.path ?? "选择解压出来的 SPT 文件夹（里面有 启动.py、工作区）。", actions: true)
                return
            }
            if self.projectScopeStarted { self.authorizedProjectURL?.stopAccessingSecurityScopedResource() }
            self.projectScopeStarted = project.startAccessingSecurityScopedResource()
            self.authorizedProjectURL = project
            do {
                let bookmark = try project.bookmarkData(options: .withSecurityScope,
                                                       includingResourceValuesForKeys: nil, relativeTo: nil)
                UserDefaults.standard.set(bookmark, forKey: self.projectBookmarkKey)
            } catch {
                self.showStartupPage(title: "目录权限未能保存", detail: "这次可使用所选目录；下次可能需要重新选择。请点“重试”。", actions: true)
                return
            }
            self.startWorkspace()
        }
    }

    @objc private func retryWorkspaceStartup() { startWorkspace() }

    private func checkWorkspaceHealth(_ completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8766/api/health")!)
        request.timeoutInterval = 2
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let payload = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let healthy = (response as? HTTPURLResponse)?.statusCode == 200
                && payload?["app"] as? String == "media-workspace"
            DispatchQueue.main.async { completion(healthy) }
        }.resume()
    }

    private func launchWorkspace(_ attempt: UUID, destination: URL) {
        guard let project = authorizedProjectURL else { failWorkspaceStartup(attempt); return }
        let launcher = project.appendingPathComponent("启动.py")
        let process = Process()
        startupProcess = process
        // Keep filesystem and process startup off the AppKit thread. Respect
        // macOS file protections; a denied or stalled launch gets a visible path.
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let python = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                          "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3"]
                .first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [launcher.path, "--no-open"]
            process.currentDirectoryURL = project
            do {
                let logDirectory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                    .appendingPathComponent("MediaDesk", isDirectory: true)
                try FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
                let logURL = logDirectory.appendingPathComponent("startup.log")
                if !FileManager.default.fileExists(atPath: logURL.path) {
                    FileManager.default.createFile(atPath: logURL.path, contents: nil,
                                                  attributes: [.posixPermissions: 0o600])
                }
                let log = try FileHandle(forWritingTo: logURL)
                try log.seekToEnd()
                process.standardOutput = log
                process.standardError = log
                process.terminationHandler = { _ in try? log.close() }
                try process.run()
            }
            catch {
                DispatchQueue.main.async {
                    guard let self = self, self.startupAttempt == attempt else { return }
                    self.failWorkspaceStartup(attempt)
                }
            }
        }
        pollWorkspaceStartup(attempt, destination: destination, deadline: Date().addingTimeInterval(10))
    }

    private func pollWorkspaceStartup(_ attempt: UUID, destination: URL, deadline: Date) {
        guard startupAttempt == attempt else { return }
        checkWorkspaceHealth { [weak self] healthy in
            guard let self = self, self.startupAttempt == attempt else { return }
            if healthy { self.finishWorkspaceStartup(attempt, destination: destination); return }
            guard Date() < deadline else { self.failWorkspaceStartup(attempt); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.pollWorkspaceStartup(attempt, destination: destination, deadline: deadline)
            }
        }
    }

    private func finishWorkspaceStartup(_ attempt: UUID, destination: URL) {
        guard startupAttempt == attempt else { return }
        startupAttempt = nil
        showingStartupPage = false
        showNativeWorkspace()
    }

    private func failWorkspaceStartup(_ attempt: UUID) {
        guard startupAttempt == attempt else { return }
        startupAttempt = nil
        showStartupPage(title: "SPT 还没启动好", detail: "可以点「打开 SPT 文件夹」重新授权，或点「重试」。如果一直不行：确认电脑装了 Python 3（终端运行 python3 --version；没有就按提示安装），启动记录在 ~/Library/Application Support/MediaDesk/startup.log。", actions: true)
    }

    private func showStartupPage(title: String, detail: String, actions: Bool = true) {
        showingStartupPage = true
        let page = NSView()
        let heading = NSTextField(labelWithString: title)
        heading.font = .systemFont(ofSize: 25, weight: .semibold)
        let text = NSTextField(wrappingLabelWithString: detail)
        text.textColor = .secondaryLabelColor
        text.font = .systemFont(ofSize: 14)
        let stack = NSStackView(views: [heading, text])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 18
        if actions {
            let open = NSButton(title: "打开 SPT 文件夹", target: self, action: #selector(chooseProjectFolder))
            open.bezelStyle = .rounded
            let retry = NSButton(title: "重试", target: self, action: #selector(retryWorkspaceStartup))
            retry.bezelStyle = .rounded
            let buttons = NSStackView(views: [open, retry])
            buttons.spacing = 12
            stack.addArrangedSubview(buttons)
        }
        stack.translatesAutoresizingMaskIntoConstraints = false
        page.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: page.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: page.centerYAnchor, constant: -40),
            stack.widthAnchor.constraint(equalToConstant: 540),
        ])
        window.contentView = page
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let origin = message.frameInfo.securityOrigin
        guard origin.protocol == "http",
              origin.host == "127.0.0.1",
              origin.port == 8766,
              isWorkspaceURL(message.frameInfo.request.url),
              isWorkspaceURL(webView.url) else { return }

        if message.name == "openPublishing" {
            openPublishing(message.body)
            return
        }
        if message.name == "chooseWorkspace" {
            chooseWorkspaceFolder()
            return
        }
        if ["runPublishingQueue", "previewPublishingQueue"].contains(message.name) {
            guard #available(macOS 14.0, *) else { return }
            let coordinator = queueCoordinator()
            if message.name == "runPublishingQueue" { coordinator.start(); return }
            guard let arguments = message.body as? [String: Any],
                  let identifier = arguments["queue_id"] as? String,
                  !identifier.isEmpty, identifier.count <= 100 else { return }
            if let pane = coordinator.preview(queueID: identifier, parentWindow: window, onReturn: { [weak self] in
                guard let self = self else { return }
                self.window.contentView = self.webView
                self.window.title = "SPT"
            }) {
                window.contentView = pane
                window.title = "SPT · 发布任务"
            }
            return
        }
        if ["startRednoteUpload", "cancelRednoteUpload", "previewRednoteUpload"].contains(message.name) {
            handleRednoteUpload(message.name, body: message.body)
            return
        }
        guard message.name == "chooseMedia", !selectingFiles else { return }

        selectingFiles = true
        let panel = NSOpenPanel()
        panel.title = "选择本地素材"
        panel.message = "加入本地素材库，尚未上传到互联网。"
        panel.prompt = "添加素材"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.resolvesAliases = true
        panel.allowedContentTypes = [.movie, .image]
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            self.selectingFiles = false
            guard isWorkspaceURL(self.webView.url) else { return }
            let paths = response == .OK ? panel.urls.map { $0.path } : []
            guard let data = try? JSONSerialization.data(withJSONObject: paths),
                  let json = String(data: data, encoding: .utf8) else { return }
            let safeJSON = json
                .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
                .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
            self.webView.evaluateJavaScript("if (typeof window.mediaUploaderNativeFiles === 'function') { window.mediaUploaderNativeFiles(\(safeJSON)); }")
        }
    }

    /// 设置 › 工作区位置：用系统面板选文件夹，把路径交回页面（页面再交给本地服务检查和保存）。
    private func chooseWorkspaceFolder() {
        guard !selectingFiles else { return }
        selectingFiles = true
        let panel = NSOpenPanel()
        panel.title = "选择工作区文件夹"
        panel.message = "SPT 会读取这个文件夹里的作品、提示词、素材和便签，不会搬动文件。"
        panel.prompt = "使用这个文件夹"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = true
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            self.selectingFiles = false
            guard response == .OK, let url = panel.url, isWorkspaceURL(self.webView.url),
                  let data = try? JSONSerialization.data(withJSONObject: [url.path]),
                  let json = String(data: data, encoding: .utf8) else { return }
            let safeJSON = json
                .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
                .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
            self.webView.evaluateJavaScript("if (typeof window.sptWorkspaceChosen === 'function') { window.sptWorkspaceChosen(\(safeJSON)[0]); }")
        }
    }

    @available(macOS 14.0, *)
    private func queueCoordinator() -> PublishingQueueCoordinator {
        if let existing = publishingQueueCoordinator as? PublishingQueueCoordinator { return existing }
        let coordinator = PublishingQueueCoordinator()
        publishingQueueCoordinator = coordinator
        return coordinator
    }

    private func handleRednoteUpload(_ action: String, body: Any) {
        guard let arguments = body as? [String: Any] else { return }
        guard #available(macOS 14.0, *) else {
            nativeUploadStatus(id: "", state: "failed", message: "后台上传需要 macOS 14 或以上版本。")
            return
        }
        let coordinator = rednoteCoordinator()
        if action == "startRednoteUpload" {
            guard let accountID = arguments["account_id"] as? String,
                  let draftID = arguments["draft_id"] as? String,
                  !accountID.isEmpty, accountID.count <= 200,
                  !draftID.isEmpty, draftID.count <= 200 else { return }
            coordinator.start(accountID: accountID, draftID: draftID)
            return
        }
        guard let identifier = (arguments["job_id"] ?? arguments["id"]) as? String,
              !identifier.isEmpty, identifier.count <= 200 else { return }
        if action == "cancelRednoteUpload" {
            coordinator.cancel(jobID: identifier)
        } else if action == "previewRednoteUpload" {
            if let pane = coordinator.preview(jobID: identifier, parentWindow: window,
                onReturn: { [weak self] in
                    guard let self = self else { return }
                    self.window.contentView = self.webView
                    self.window.title = "SPT"
                    self.window.makeKeyAndOrderFront(nil)
                }) {
                window.contentView = pane
                window.title = "SPT"
                window.makeKeyAndOrderFront(nil)
            } else { openUploadFallback(identifier) }
        }
    }

    private func openUploadFallback(_ identifier: String) {
        guard !openingUploadFallback else { return }
        openingUploadFallback = true
        var components = URLComponents(string: "http://127.0.0.1:8766/api/publishing/upload")!
        components.queryItems = [URLQueryItem(name: "id", value: identifier)]
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let result = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.openingUploadFallback = false
                guard error == nil, (response as? HTTPURLResponse)?.statusCode == 200,
                      let job = result?["job"] as? [String: Any],
                      let accountID = job["account_id"] as? String,
                      let draftID = job["draft_id"] as? String,
                      !accountID.isEmpty, accountID.count <= 200,
                      !draftID.isEmpty, draftID.count <= 200 else {
                    self.nativeUploadStatus(id: identifier, state: "needs_attention",
                        message: result?["error"] as? String ?? "无法读取原上传任务，请从账号页打开并核对平台草稿。")
                    return
                }
                self.nativeUploadStatus(id: identifier, state: job["state"] as? String ?? "needs_attention",
                    message: "正在打开账号官方页，请核对平台草稿；未重新上传。")
                self.openPublishing(["account_id": accountID, "draft_id": draftID])
            }
        }.resume()
    }

    @available(macOS 14.0, *)
    private func rednoteCoordinator() -> RednoteUploadCoordinator {
        if let existing = rednoteUploadCoordinator as? RednoteUploadCoordinator { return existing }
        let coordinator = RednoteUploadCoordinator(onChange: { [weak self] identifier, state, message in
            self?.nativeUploadStatus(id: identifier, state: state, message: message)
        }, onNeedsLogin: { [weak self] accountID, draftID in
            DispatchQueue.main.async {
                self?.openPublishing(["account_id": accountID, "draft_id": draftID])
            }
        })
        rednoteUploadCoordinator = coordinator
        return coordinator
    }

    private func nativeUploadStatus(id: String, state: String, message: String) {
        guard Thread.isMainThread else {
            DispatchQueue.main.async { [weak self] in self?.nativeUploadStatus(id: id, state: state, message: message) }
            return
        }
        guard isWorkspaceURL(webView.url),
              let data = try? JSONSerialization.data(withJSONObject: [
                  "id": id, "job_id": id, "state": state, "message": message
              ]), let json = String(data: data, encoding: .utf8) else { return }
        let safe = json.replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
        webView.evaluateJavaScript("if (typeof window.mediaNativeUploadStatus === 'function') { window.mediaNativeUploadStatus(\(safe)); }")
    }

    private func openPublishing(_ body: Any) {
        guard !openingPublishing, let arguments = body as? [String: Any],
              let accountID = arguments["account_id"] as? String,
              !accountID.isEmpty, accountID.count <= 200 else { return }
        let draftID = arguments["draft_id"] as? String
        if let draftID = draftID, draftID.count > 200 { return }
        // Only known targets: "meta_suite" opens Instagram/Facebook accounts at Meta Business Suite.
        let target = arguments["target"] as? String
        if let target = target, target != "meta_suite" { return }
        publishingReturnsToNative = window.contentView === nativeWorkspace
        guard #available(macOS 14.0, *) else {
            showPublishingError("独立持久登录空间需要 macOS 14 或以上版本。现有工作台和手动发布包仍可使用。")
            return
        }
        openingPublishing = true
        PublishingAPI.load(accountID: accountID, draftID: draftID, target: target) { [weak self] result in
            guard let self = self else { return }
            self.openingPublishing = false
            switch result {
            case .success(let payload):
                do {
                    if let existing = self.publishingWorkspace as? PublishingWorkspace,
                       existing.matches(payload) {
                        existing.show()
                    } else {
                        let pane = try PublishingWorkspace(payload: payload, hostWindow: self.window,
                            onReturn: { [weak self] draftID in
                                guard let self = self else { return }
                                if self.publishingReturnsToNative {
                                    self.showNativeWorkspace()
                                    return
                                }
                                self.window.contentView = self.webView
                                self.window.title = "SPT"
                                self.window.makeKeyAndOrderFront(nil)
                                if let draftID = draftID,
                                   let data = try? JSONSerialization.data(withJSONObject: [draftID]),
                                   let json = String(data: data, encoding: .utf8) {
                                    self.webView.evaluateJavaScript("window.MediaDesk?.selectDraft((\(json))[0]); window.location.hash = 'publish';")
                                }
                            })
                        self.publishingWorkspace = pane
                        pane.show()
                    }
                    self.publishingOpenResult(["ok": true, "opened": true])
                } catch { self.showPublishingError(error.localizedDescription) }
            case .failure(let error): self.showPublishingError(error.localizedDescription)
            }
        }
    }

    private func showPublishingError(_ message: String) {
        publishingOpenResult(["ok": false, "error": message])
        let alert = NSAlert()
        alert.messageText = "发布工作区暂时无法打开"
        alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window)
    }

    private func publishingOpenResult(_ result: [String: Any]) {
        guard isWorkspaceURL(webView.url),
              let data = try? JSONSerialization.data(withJSONObject: result),
              let json = String(data: data, encoding: .utf8) else { return }
        let safe = json.replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
        webView.evaluateJavaScript("if (typeof window.mediaPublishingOpenResult === 'function') { window.mediaPublishingOpenResult(\(safe)); }")
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if showingStartupPage, action.request.url?.absoluteString == "about:blank" {
            decisionHandler(.allow)
            return
        }
        if isWorkspaceURL(action.request.url) {
            if action.targetFrame?.isMainFrame != false,
               let path = action.request.url?.path,
               path == "/" {
                decisionHandler(.cancel)
                showNativeWorkspace()
                return
            }
            decisionHandler(action.shouldPerformDownload ? (isExportURL(action.request.url) ? .download : .cancel) : .allow)
            return
        }
        if isTrustedUserLink(action), let url = action.request.url, url.scheme == "https" {
            if action.targetFrame == nil {
                // New-window links are handled exactly once in createWebViewWith.
                decisionHandler(.allow)
                return
            }
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    private func isTrustedUserLink(_ action: WKNavigationAction) -> Bool {
        let origin = action.sourceFrame.securityOrigin
        return action.navigationType == .linkActivated
            && origin.protocol == "http" && origin.host == "127.0.0.1" && origin.port == 8766
            && isWorkspaceURL(action.sourceFrame.request.url) && isWorkspaceURL(webView.url)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard action.targetFrame == nil, isTrustedUserLink(action) else { return nil }
        if let url = action.request.url, url.scheme == "https" {
            NSWorkspace.shared.open(url)
        } else if isWorkspaceURL(action.request.url) {
            webView.load(action.request)
        }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if showingStartupPage, response.isForMainFrame, response.response.url?.absoluteString == "about:blank" {
            decisionHandler(.allow)
            return
        }
        // The publishing tools are shown in a frame inside the SPT page; they come from the same local server.
        guard isWorkspaceURL(response.response.url) else {
            decisionHandler(.cancel)
            return
        }
        let disposition = (response.response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition")?.lowercased() ?? ""
        if disposition.hasPrefix("attachment") || !response.canShowMIMEType {
            decisionHandler(isExportURL(response.response.url) ? .download : .cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, navigationAction action: WKNavigationAction, didBecome download: WKDownload) {
        beginDownload(download)
    }

    func webView(_ webView: WKWebView, navigationResponse response: WKNavigationResponse, didBecome download: WKDownload) {
        beginDownload(download)
    }

    private func beginDownload(_ download: WKDownload) {
        guard isExportURL(download.originalRequest?.url) else {
            download.cancel(nil)
            return
        }
        downloads[ObjectIdentifier(download)] = DownloadSave(download)
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let key = ObjectIdentifier(download)
        guard isExportURL(response.url), let save = downloads[key],
              let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            downloads.removeValue(forKey: key)
            completionHandler(nil)
            showSaveError("这次导出没有拿到文件，请再试一次。")
            return
        }
        let panel = NSSavePanel()
        panel.title = "导出 SPT 资产表"
        panel.prompt = "保存"
        panel.canCreateDirectories = true
        panel.isExtensionHidden = false
        let filename = (suggestedFilename as NSString).lastPathComponent
        let day = DateFormatter()
        day.dateFormat = "yyyy-MM-dd"
        panel.nameFieldStringValue = filename.isEmpty ? "SPT-资产-\(day.string(from: Date()))" : filename
        panel.beginSheetModal(for: window) { [weak self] result in
            guard let self = self else { completionHandler(nil); return }
            guard result == .OK, let destination = panel.url else {
                self.downloads.removeValue(forKey: key)
                completionHandler(nil)
                return
            }
            save.destination = destination
            // End the save panel's ViewBridge completion before talking to WebKit.
            // The network subprocess writes only to an unprotected system temporary
            // directory; native file work handles the user-selected destination.
            self.exportFileQueue.async {
                let stagingDirectory = FileManager.default.temporaryDirectory
                    .appendingPathComponent("MediaDesk-export-\(UUID().uuidString)", isDirectory: true)
                do {
                    let attributes = FileManager.default.fileExists(atPath: destination.path)
                        ? try FileManager.default.attributesOfItem(atPath: destination.path) : nil
                    try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: false,
                                                            attributes: [.posixPermissions: 0o700])
                    let staging = stagingDirectory.appendingPathComponent("payload")
                    DispatchQueue.main.async {
                        guard self.downloads[key] === save else {
                            self.exportFileQueue.async { try? FileManager.default.removeItem(at: stagingDirectory) }
                            completionHandler(nil)
                            return
                        }
                        save.existingAttributes = attributes
                        save.stagingDirectory = stagingDirectory
                        save.staging = staging
                        completionHandler(staging)
                    }
                } catch {
                    try? FileManager.default.removeItem(at: stagingDirectory)
                    DispatchQueue.main.async {
                        self.downloads.removeValue(forKey: key)
                        completionHandler(nil)
                        self.showSaveError(error.localizedDescription)
                    }
                }
            }
        }
    }

    func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse,
                  newRequest request: URLRequest, decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
        decisionHandler(isExportURL(request.url) ? .allow : .cancel)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let save = downloads.removeValue(forKey: ObjectIdentifier(download)),
              let destination = save.destination, let staging = save.staging else { return }
        exportFileQueue.async {
            let destinationStaging = destination.deletingLastPathComponent()
                .appendingPathComponent(".media-desk-save-\(UUID().uuidString)")
            defer {
                if let directory = save.stagingDirectory { try? FileManager.default.removeItem(at: directory) }
                try? FileManager.default.removeItem(at: destinationStaging)
            }
            do {
                // Copy first so exports to another volume still replace atomically.
                try FileManager.default.copyItem(at: staging, to: destinationStaging)
                if let original = save.existingAttributes {
                    let current = try FileManager.default.attributesOfItem(atPath: destination.path)
                    let fields: [FileAttributeKey] = [.systemFileNumber, .size, .modificationDate]
                    guard fields.allSatisfy({ (original[$0] as? NSObject) == (current[$0] as? NSObject) }) else {
                        throw NSError(domain: "MediaDesk", code: 1, userInfo: [NSLocalizedDescriptionKey: "目标文件在保存过程中发生了变化，请选择另一个文件名后重试。"])
                    }
                    _ = try FileManager.default.replaceItemAt(destination, withItemAt: destinationStaging)
                } else {
                    try FileManager.default.moveItem(at: destinationStaging, to: destination)
                }
            } catch {
                DispatchQueue.main.async { self.showSaveError(error.localizedDescription) }
            }
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        guard let save = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        if let directory = save.stagingDirectory {
            exportFileQueue.async { try? FileManager.default.removeItem(at: directory) }
        }
        if (error as NSError).code != NSURLErrorCancelled { showSaveError(error.localizedDescription) }
    }

    private func showSaveError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "导出文件保存失败"
        alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        let alert = NSAlert()
        alert.messageText = "工作台还没有启动"
        alert.informativeText = "请重新打开 SPT。后台服务就绪后，可按 ⌘R 重新载入。"
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window)
    }
}

@main
enum MediaDeskApplication {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}
