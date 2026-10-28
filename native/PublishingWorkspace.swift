import AppKit
import WebKit
import UniformTypeIdentifiers

struct PublishingAccount: Decodable {
    let id: String
    let name: String
    let platform: String
    let handle: String
}

struct PublishingPlatform: Decodable {
    let id: String
    let name: String
    let publish_url: String
    let login_note: String?
    let allowed_domains: [String]
}

struct PublishingDraft: Decodable {
    let id: String
    let title: String
    let body: String
    let fingerprint: String
    let status: String
}

struct PublishingMedia: Decodable {
    let id: String
    let name: String
    let path: String
    let size: Int64
    let mime_type: String
    let order: Int
    let available: Bool
    let issue: String?
}

struct PublishingPayload: Decodable {
    let account: PublishingAccount
    let platform: PublishingPlatform
    let profile_id: String
    let draft: PublishingDraft?
    let media: [PublishingMedia]
    let can_upload_current: Bool
    let issues: [String]
}

private final class PublishingSidebarDocument: NSView {
    override var isFlipped: Bool { true }
}

/// Append our app identity and, only for an exact same-build system engine,
/// its installed Safari engine version. Keep WebKit's default UA and leave
/// the platform's real feature detection untouched.
enum RednoteBrowserIdentity {
    static func apply(to configuration: WKWebViewConfiguration) {
        var identity = "MediaDesk/0.6"
        let safari = plist("/Applications/Safari.app/Contents/Info.plist")
        let webkit = plist("/System/Library/Frameworks/WebKit.framework/Resources/Info.plist")
        if let safariBuild = safari?["CFBundleVersion"] as? String,
           let webkitBuild = webkit?["CFBundleVersion"] as? String,
           let version = safari?["CFBundleShortVersionString"] as? String,
           safariBuild == webkitBuild,
           numericVersion(safariBuild), numericVersion(webkitBuild), numericVersion(version) {
            identity += " (system WebKit; Safari engine Version/\(version))"
        }
        configuration.applicationNameForUserAgent = identity
    }

    /// The installed Safari's own "Version/x Safari/605.1.15" suffix on the system WebKit UA.
    static func applySafari(to configuration: WKWebViewConfiguration) {
        let safari = plist("/Applications/Safari.app/Contents/Info.plist")
        let version = (safari?["CFBundleShortVersionString"] as? String).flatMap { numericVersion($0) ? $0 : nil } ?? "17.6"
        configuration.applicationNameForUserAgent = "Version/\(version) Safari/605.1.15"
    }

    private static func plist(_ path: String) -> [String: Any]? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { return nil }
        return (try? PropertyListSerialization.propertyList(from: data, options: [], format: nil)) as? [String: Any]
    }

    private static func numericVersion(_ value: String) -> Bool {
        value.range(of: "^[0-9]+(?:\\.[0-9]+)*$", options: .regularExpression) != nil
    }
}

/// This client reads our local records only. It never accesses platform credentials.
enum PublishingAPI {
    static func load(accountID: String, draftID: String?, target: String? = nil, completion: @escaping (Result<PublishingPayload, Error>) -> Void) {
        var components = URLComponents(string: "http://127.0.0.1:8766/api/publishing/workspace")!
        components.queryItems = [URLQueryItem(name: "account_id", value: accountID)]
        if let draftID = draftID, !draftID.isEmpty {
            components.queryItems!.append(URLQueryItem(name: "draft_id", value: draftID))
        }
        if let target = target, !target.isEmpty {
            components.queryItems!.append(URLQueryItem(name: "target", value: target))
        }
        var request = URLRequest(url: components.url!)
        request.timeoutInterval = 20
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { data, response, error in
            let result: Result<PublishingPayload, Error>
            do {
                if let error = error { throw error }
                guard let data = data, let response = response as? HTTPURLResponse else {
                    throw failure("本地工作台没有返回账号资料。")
                }
                guard (200...299).contains(response.statusCode) else {
                    let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    throw failure(value?["error"] as? String ?? "发布工作区暂时无法打开。")
                }
                result = .success(try JSONDecoder().decode(PublishingPayload.self, from: data))
            } catch { result = .failure(error) }
            DispatchQueue.main.async { completion(result) }
        }.resume()
    }

    static func failure(_ message: String) -> NSError {
        NSError(domain: "MediaDesk.Publishing", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

/// A child window for a login popup an official page opens with window.open. It shares the
/// account's website data store through the configuration WebKit hands us, follows the same
/// domain rules as the pane that opened it, and closes itself when the page calls window.close().
@available(macOS 14.0, *)
private final class LoginPopup: NSObject, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    let webView: WKWebView
    private let panel: NSWindow
    private weak var owner: PublishingWorkspace?
    private var urlObservation: NSKeyValueObservation?

    init(configuration: WKWebViewConfiguration, owner: PublishingWorkspace, features: WKWindowFeatures) {
        self.owner = owner
        webView = WKWebView(frame: .zero, configuration: configuration)
        let width = min(max(CGFloat(truncating: features.width ?? 620), 480), 960)
        let height = min(max(CGFloat(truncating: features.height ?? 720), 520), 960)
        panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: height),
                         styleMask: [.titled, .closable, .resizable, .miniaturizable],
                         backing: .buffered, defer: false)
        super.init()
        panel.title = "登录"
        panel.isReleasedWhenClosed = false
        panel.delegate = self
        panel.contentView = webView
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsLinkPreview = false
        urlObservation = webView.observe(\.url, options: [.new]) { [weak self] view, _ in
            self?.panel.title = view.url?.host ?? "登录"
        }
    }

    func show(above host: NSWindow) {
        let frame = host.frame
        panel.setFrameOrigin(NSPoint(x: frame.midX - panel.frame.width / 2, y: frame.midY - panel.frame.height / 2))
        panel.makeKeyAndOrderFront(nil)
    }

    func close() { panel.close() }

    // MARK: WKUIDelegate

    func webViewDidClose(_ webView: WKWebView) { panel.close() }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // A popup opened from the popup stays in this window.
        if let url = action.request.url, owner?.permitted(url) == true { webView.load(URLRequest(url: url)) }
        return nil
    }

    // MARK: WKNavigationDelegate — the same rules as the pane that opened us

    /// Google's sign-in popup ends on the business page itself instead of calling window.close().
    /// Once the popup sits on a platform page that is not a login host, continue there in the
    /// main pane and close the popup (用户 2026-10-24 "登录了，可是没有回到主窗口").
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let owner = owner, let url = webView.url, owner.permitted(url) else { return }
        let host = (url.host ?? "").lowercased()
        let loginHost = host.hasPrefix("accounts.") || host.hasPrefix("login.") || host.hasPrefix("myaccount.")
            || host.contains("oauth") || url.path.lowercased().contains("/login")
        guard !loginHost else { return }
        owner.landed(on: url)
        DispatchQueue.main.async { [weak self] in self?.close() }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let owner = owner, let url = action.request.url else { decisionHandler(.cancel); return }
        if action.targetFrame?.isMainFrame == false {
            decisionHandler(owner.publicHTTPS(url) ? .allow : .cancel)
            return
        }
        if url.absoluteString == "about:blank" || owner.permitted(url) { decisionHandler(.allow); return }
        // A login popup leaving the platform's domains (Google sign-in, which refuses embedded
        // windows anyway) continues in the system browser instead of staying blank (用户 2026-10-24).
        if owner.publicHTTPS(url) {
            NSWorkspace.shared.open(url)
            owner.showStatus("登录页已在系统浏览器打开。")
            DispatchQueue.main.async { [weak self] in self?.close() }
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard let owner = owner else { decisionHandler(.cancel); return }
        let allowed = response.isForMainFrame ? owner.permitted(response.response.url) : owner.publicHTTPS(response.response.url)
        decisionHandler(allowed && response.canShowMIMEType ? .allow : .cancel)
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        urlObservation = nil
        webView.stopLoading()
        webView.navigationDelegate = nil
        webView.uiDelegate = nil
        owner?.popupClosed(self)
    }
}

/// An account-specific pane operated by the user. It carries no local message
/// handlers, credential extraction or automatic publishing controls. The
/// separate rednote upload coordinator owns its narrowly scoped DOM adapter.
@available(macOS 14.0, *)
final class PublishingWorkspace: NSObject, WKNavigationDelegate, WKUIDelegate {
    private let payload: PublishingPayload
    private let onReturn: (String?) -> Void
    private let window: NSWindow
    private(set) var view: NSView!
    private var webView: WKWebView!
    private var address: NSTextField!
    private var status: NSTextField!
    private var selectingFiles = false
    private var lastURLObservation: NSKeyValueObservation?
    private var sessionPrepared = false
    private var sessionWarning: String?
    private var sessionNavigationFinished = false
    private var sessionAccepted = false
    private var sessionRouteRevision = 0
    private var sessionProbeTimer: Timer?
    private var popups: [LoginPopup] = []

    deinit { sessionProbeTimer?.invalidate() }

    init(payload: PublishingPayload, hostWindow: NSWindow, onReturn: @escaping (String?) -> Void) throws {
        guard let identifier = UUID(uuidString: payload.profile_id),
              let initialURL = URL(string: payload.platform.publish_url) else {
            throw PublishingAPI.failure("账号登录空间配置无效。")
        }
        self.payload = payload
        self.onReturn = onReturn
        self.window = hostWindow
        super.init()
        guard permitted(initialURL) else { throw PublishingAPI.failure("发布入口不在此平台的官方域名范围内。") }
        let configuration = WKWebViewConfiguration()
        if payload.account.platform == "xiaohongshu" {
            RednoteBrowserIdentity.apply(to: configuration)
        } else if payload.account.platform.hasPrefix("google") {
            // Google 登录只认完整的 Safari 标识；这里报的是本机真实安装的 Safari 版本（用户 2026-10-24 "有办法解决吗"）。
            RednoteBrowserIdentity.applySafari(to: configuration)
        }
        configuration.websiteDataStore = payload.account.platform == "xiaohongshu"
            ? RednoteSessionVault.shared.dataStore(profile: identifier)
            : WKWebsiteDataStore(forIdentifier: identifier)
        configuration.userContentController = WKUserContentController()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = [.audio, .video]
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.allowsLinkPreview = false
        buildView()
        lastURLObservation = webView.observe(\.url, options: [.new]) { [weak self] view, _ in
            self?.address.stringValue = view.url?.host ?? ""
            self?.address.toolTip = view.url?.absoluteString
            self?.observeSessionRoute(view.url)
        }
        if payload.account.platform == "xiaohongshu" {
            sessionProbeTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                self?.probeAuthenticatedSession()
            }
            RednoteSessionVault.shared.prepare(profile: identifier, onError: { [weak self] message in
                self?.sessionWarning = message
                self?.showStatus(message)
            }, completion: { [weak self] _ in
                guard let self = self else { return }
                self.sessionPrepared = true
                self.webView.load(URLRequest(url: initialURL))
            })
        } else {
            sessionPrepared = true
            webView.load(URLRequest(url: initialURL))
        }
    }

    func show() {
        window.contentView = view
        window.title = "SPT · \(payload.account.name)"
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func refresh() { if sessionPrepared { webView.reload() } }

    func matches(_ candidate: PublishingPayload) -> Bool {
        payload.account.id == candidate.account.id
            && payload.platform.id == candidate.platform.id
            && payload.draft?.id == candidate.draft?.id
            && payload.draft?.fingerprint == candidate.draft?.fingerprint
    }

    private func buildView() {
        let content = NSView()
        self.view = content
        let toolbar = NSStackView()
        toolbar.orientation = .horizontal
        toolbar.spacing = 8
        toolbar.edgeInsets = NSEdgeInsets(top: 8, left: 12, bottom: 8, right: 12)
        toolbar.addArrangedSubview(button("返回工作台", #selector(returnToWorkspace)))
        let account = NSTextField(labelWithString: payload.account.name)
        account.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        account.toolTip = payload.account.handle
        toolbar.addArrangedSubview(account)
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        toolbar.addArrangedSubview(spacer)
        toolbar.addArrangedSubview(button("←", #selector(goBack)))
        toolbar.addArrangedSubview(button("刷新", #selector(reloadPage)))
        address = NSTextField(labelWithString: URL(string: payload.platform.publish_url)?.host ?? "")
        address.isSelectable = true
        address.lineBreakMode = .byTruncatingMiddle
        address.textColor = .secondaryLabelColor
        address.font = NSFont.systemFont(ofSize: 10)
        address.toolTip = payload.platform.publish_url
        address.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        address.widthAnchor.constraint(lessThanOrEqualToConstant: 165).isActive = true
        toolbar.addArrangedSubview(address)
        let more = NSPopUpButton()
        more.pullsDown = true
        more.bezelStyle = .rounded
        let menu = NSMenu()
        menu.addItem(withTitle: "…", action: nil, keyEquivalent: "")
        let home = menu.addItem(withTitle: "回发布入口", action: #selector(goPublish), keyEquivalent: "")
        home.target = self
        let browser = menu.addItem(withTitle: "在系统浏览器打开", action: #selector(openExternal), keyEquivalent: "")
        browser.target = self
        let help = menu.addItem(withTitle: "登录与会话说明", action: #selector(showLoginHelp), keyEquivalent: "")
        help.target = self
        more.menu = menu
        more.toolTip = payload.platform.login_note
        toolbar.addArrangedSubview(more)
        status = wrappingLabel("", size: 11)
        status.preferredMaxLayoutWidth = 0
        status.isHidden = true
        let body = NSView()
        let stack = NSStackView(views: [toolbar, status!, body] as [NSView])
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 0
        content.addSubview(stack)
        stack.translatesAutoresizingMaskIntoConstraints = false
        body.addSubview(webView)
        webView.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            webView.topAnchor.constraint(equalTo: body.topAnchor),
            webView.bottomAnchor.constraint(equalTo: body.bottomAnchor),
            webView.trailingAnchor.constraint(equalTo: body.trailingAnchor)
        ])
        if payload.draft != nil {
            let sidebar = buildSidebar()
            body.addSubview(sidebar)
            sidebar.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                sidebar.leadingAnchor.constraint(equalTo: body.leadingAnchor),
                sidebar.topAnchor.constraint(equalTo: body.topAnchor),
                sidebar.bottomAnchor.constraint(equalTo: body.bottomAnchor),
                sidebar.widthAnchor.constraint(equalToConstant: 280),
                webView.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor)
            ])
        } else {
            webView.leadingAnchor.constraint(equalTo: body.leadingAnchor).isActive = true
        }
    }

    private func buildSidebar() -> NSView {
        let scroll = NSScrollView()
        scroll.appearance = NSAppearance(named: .aqua)
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = true
        scroll.backgroundColor = NSColor(calibratedRed: 0.97, green: 0.96, blue: 0.99, alpha: 1)
        let document = PublishingSidebarDocument()
        scroll.documentView = document
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        document.addSubview(stack)
        document.translatesAutoresizingMaskIntoConstraints = false
        stack.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            stack.leadingAnchor.constraint(equalTo: document.leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: document.trailingAnchor, constant: -14),
            stack.topAnchor.constraint(equalTo: document.topAnchor, constant: 16),
            stack.bottomAnchor.constraint(equalTo: document.bottomAnchor, constant: -20)
        ])
        stack.addArrangedSubview(wrappingLabel(payload.platform.name, size: 11, color: .secondaryLabelColor))
        stack.addArrangedSubview(wrappingLabel(payload.account.name, size: 15, weight: .semibold))
        let session = wrappingLabel("登录状态只存在本机", size: 11, color: .secondaryLabelColor)
        session.toolTip = "下次通常可继续使用；平台过期、安全验证或注销时需重新登录。"
        stack.addArrangedSubview(session)
        stack.addArrangedSubview(separator())
        if let draft = payload.draft {
            stack.addArrangedSubview(wrappingLabel(draft.title, size: 14, weight: .semibold))
            stack.addArrangedSubview(button("复制标题", #selector(copyTitle)))
            let body = NSTextView(frame: NSRect(x: 0, y: 0, width: 252, height: 210))
            body.isEditable = false
            body.isSelectable = true
            body.string = draft.body
            body.font = NSFont.systemFont(ofSize: 12)
            body.textContainerInset = NSSize(width: 7, height: 8)
            body.isHorizontallyResizable = false
            body.textContainer?.widthTracksTextView = true
            body.autoresizingMask = [.width]
            body.drawsBackground = true
            body.backgroundColor = .textBackgroundColor
            let bodyScroll = NSScrollView()
            bodyScroll.borderType = .bezelBorder
            bodyScroll.hasVerticalScroller = true
            bodyScroll.documentView = body
            bodyScroll.translatesAutoresizingMaskIntoConstraints = false
            bodyScroll.heightAnchor.constraint(equalToConstant: 210).isActive = true
            bodyScroll.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
            stack.addArrangedSubview(bodyScroll)
            stack.addArrangedSubview(button("复制正文", #selector(copyBody)))
            stack.addArrangedSubview(wrappingLabel("素材 \(payload.media.count)", size: 12, weight: .medium))
            for media in payload.media.sorted(by: { $0.order < $1.order }) {
                let item = wrappingLabel(String(format: "%02d  ", media.order) + media.name, size: 12)
                item.toolTip = media.available ? media.path : media.issue
                if !media.available { item.textColor = .systemRed }
                stack.addArrangedSubview(item)
            }
            if !payload.can_upload_current, let issue = payload.issues.first {
                stack.addArrangedSubview(wrappingLabel(issue, size: 11, color: .secondaryLabelColor))
            }
        }
        return scroll
    }

    @objc private func showLoginHelp() {
        let alert = NSAlert()
        alert.messageText = "登录与会话"
        alert.informativeText = payload.platform.login_note ?? "登录状态只存在这台电脑上。平台让它过期、要求安全验证，或你退出登录后，需要重新登录。"
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window)
    }

    private func wrappingLabel(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular,
                               color: NSColor = .labelColor) -> NSTextField {
        let label = NSTextField(wrappingLabelWithString: text)
        label.font = NSFont.systemFont(ofSize: size, weight: weight)
        label.textColor = color
        label.isSelectable = true
        label.setContentCompressionResistancePriority(.required, for: .vertical)
        label.preferredMaxLayoutWidth = 252
        return label
    }

    private func button(_ title: String, _ selector: Selector) -> NSButton {
        let control = NSButton(title: title, target: self, action: selector)
        control.bezelStyle = .rounded
        control.font = NSFont.systemFont(ofSize: 12)
        return control
    }

    private func separator() -> NSView {
        let line = NSBox()
        line.boxType = .separator
        line.widthAnchor.constraint(equalToConstant: 252).isActive = true
        return line
    }

    fileprivate func publicHTTPS(_ url: URL?) -> Bool {
        guard let url = url, url.scheme?.lowercased() == "https", url.user == nil, url.password == nil,
              url.port == nil || url.port == 443, let host = url.host?.lowercased(), !host.isEmpty,
              host != "localhost", !host.hasSuffix(".localhost"), !host.hasSuffix(".local"),
              !host.hasSuffix(".internal"), !host.hasSuffix(".lan"), !host.hasSuffix(".home.arpa"),
              !host.contains(":"), host.range(of: "^[0-9.]+$", options: .regularExpression) == nil else { return false }
        return true
    }

    fileprivate func permitted(_ url: URL?) -> Bool {
        guard publicHTTPS(url), let host = url?.host?.lowercased() else { return false }
        return payload.platform.allowed_domains.contains { domain in
            let domain = domain.lowercased()
            return host == domain || host.hasSuffix("." + domain)
        }
    }

    @objc private func goBack() { if webView.canGoBack { webView.goBack() } }
    @objc private func goForward() { if webView.canGoForward { webView.goForward() } }
    @objc private func reloadPage() { refresh() }
    @objc private func goPublish() { if sessionPrepared, let url = URL(string: payload.platform.publish_url) { webView.load(URLRequest(url: url)) } }
    @objc private func copyTitle() { copy(payload.draft?.title ?? "") }
    @objc private func copyBody() { copy(payload.draft?.body ?? "") }
    @objc private func returnToWorkspace() { closePopups(); onReturn(payload.draft?.id) }
    private func copy(_ text: String) { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
    @objc private func openExternal() {
        guard let url = webView.url ?? URL(string: payload.platform.publish_url), publicHTTPS(url) else { return }
        let alert = NSAlert()
        alert.messageText = "在系统浏览器中打开官方页面"
        alert.informativeText = "浏览器有自己的登录状态，不会自动同步回本软件。请核对账号，并避免重复上传或发布。"
        alert.addButton(withTitle: "打开浏览器")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in
            if response == .alertFirstButtonReturn { NSWorkspace.shared.open(url) }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if action.targetFrame?.isMainFrame == false {
            // Official pages use third-party HTTPS frames for CAPTCHA/login.
            // These frames have no local bridge and cannot select local files.
            decisionHandler(publicHTTPS(url) ? .allow : .cancel)
            return
        }
        if permitted(url) { decisionHandler(.allow); return }
        if action.navigationType == .linkActivated, action.sourceFrame.isMainFrame, publicHTTPS(url) {
            NSWorkspace.shared.open(url)
        } else if action.targetFrame?.isMainFrame != false, publicHTTPS(url), (url.host ?? "").hasSuffix("google.com") {
            NSWorkspace.shared.open(url)
            showStatus("Google 登录已在系统浏览器打开。")
        } else if action.targetFrame?.isMainFrame != false {
            showStatus("此登录跳转需在系统浏览器处理，可从“…”打开。")
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // Official login buttons ("Continue with Facebook") open a popup and wait for it to report
        // back through window.opener. Give it a real child window on the same account store;
        // loading the address in this view instead left the opener waiting and the click looked dead.
        let url = action.request.url
        guard url == nil || url?.absoluteString == "about:blank" || permitted(url) else { return nil }
        let popup = LoginPopup(configuration: configuration, owner: self, features: windowFeatures)
        popups.append(popup)
        popup.show(above: window)
        return popup.webView
    }

    fileprivate func closePopups() {
        let open = popups
        popups.removeAll()
        open.forEach { $0.close() }
    }

    fileprivate func popupClosed(_ popup: LoginPopup) {
        popups.removeAll { $0 === popup }
        // The popup may have signed in on the shared data store: show that state in the pane.
        if popups.isEmpty, sessionPrepared { webView.reload() }
        window.makeKeyAndOrderFront(nil)
    }

    fileprivate func landed(on url: URL) {
        guard sessionPrepared, permitted(url) else { return }
        webView.load(URLRequest(url: url))
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, (response.response as? HTTPURLResponse)?.statusCode == 401,
           payload.account.platform == "xiaohongshu", let profile = UUID(uuidString: payload.profile_id) {
            RednoteSessionVault.shared.rejectSession(profile: profile)
            sessionAccepted = false
            sessionRouteRevision += 1
        }
        let allowed = response.isForMainFrame ? permitted(response.response.url) : publicHTTPS(response.response.url)
        guard allowed, response.canShowMIMEType else { decisionHandler(.cancel); return }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        sessionNavigationFinished = true
        observeSessionRoute(webView.url)
        probeAuthenticatedSession()
        if let warning = sessionWarning { showStatus(warning) }
        else { status.stringValue = ""; status.isHidden = true }
    }

    private func observeSessionRoute(_ url: URL?) {
        guard sessionPrepared, payload.account.platform == "xiaohongshu", permitted(url),
              let url = url, let profile = UUID(uuidString: payload.profile_id) else { return }
        if url.path.lowercased().contains("login") || URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.contains(where: { $0.name == "code" && $0.value == "401" }) == true {
            sessionAccepted = false
            sessionRouteRevision += 1
            RednoteSessionVault.shared.rejectSession(profile: profile)
        }
    }

    private func probeAuthenticatedSession() {
        guard sessionPrepared, sessionNavigationFinished, !sessionAccepted, !webView.isLoading,
              payload.account.platform == "xiaohongshu", permitted(webView.url),
              let url = webView.url, !url.path.lowercased().contains("login"),
              let profile = UUID(uuidString: payload.profile_id),
              ["/new/note-manager", "/new/home", "/publish/publish"].contains(where: url.path.hasPrefix) else { return }
        // Rendered official account controls allow local session capture again.
        // This is a page signal, not proof of server authentication; a later
        // login/401 always rejects the backup. No identity value is extracted.
        let script = """
        (() => {
          if (document.readyState !== 'complete' || /login/i.test(location.pathname)) return false;
          if (document.querySelector('input[placeholder="手机号"],input[placeholder="验证码"]')) return false;
          const visible = el => !!el && el.getClientRects().length > 0;
          const avatar = document.querySelector('#header-area .user-info > img.user_avatar');
          const name = document.querySelector('#header-area .user-info > span.name-box');
          const accountControls = visible(avatar) && visible(name) && !!name.textContent.trim();
          return accountControls || !!document.querySelector('input.upload-input[type="file"],.ProseMirror[contenteditable="true"]');
        })()
        """
        let revision = sessionRouteRevision
        webView.evaluateJavaScript(script) { [weak self] value, _ in
            guard let self = self, value as? Bool == true, self.webView.url == url,
                  self.sessionRouteRevision == revision, self.sessionNavigationFinished,
                  !self.webView.isLoading, !self.sessionAccepted else { return }
            self.sessionAccepted = true
            RednoteSessionVault.shared.acceptSession(profile: profile)
        }
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        sessionNavigationFinished = false
        sessionRouteRevision += 1
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        showStatus("加载失败：\(error.localizedDescription)")
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let source = frame.securityOrigin
        let sourceURL = URL(string: "\(source.protocol)://\(source.host)" + (source.port == 0 || source.port == 443 ? "" : ":\(source.port)"))
        guard frame.isMainFrame, permitted(sourceURL), permitted(webView.url), !selectingFiles else {
            completionHandler(nil); return
        }
        selectingFiles = true
        if payload.can_upload_current, !payload.media.isEmpty, payload.draft != nil {
            offerCurrentMedia(multiple: parameters.allowsMultipleSelection, completion: completionHandler)
        } else { chooseManual(multiple: parameters.allowsMultipleSelection, completion: completionHandler) }
    }

    private func offerCurrentMedia(multiple: Bool, completion: @escaping ([URL]?) -> Void) {
        let alert = NSAlert()
        alert.messageText = "向 \(payload.platform.name) 选择上传素材"
        alert.informativeText = "本机账号档案：\(payload.account.name)（\(payload.account.handle)）。请确认网页里登录的也是这个账号。\n\n" +
            (multiple ? "可按保存顺序选择本条全部 \(payload.media.count) 个已核对素材。" : "此上传入口每次仅接收一个文件，将打开本条素材所在目录，由你选择对应文件。")
        alert.addButton(withTitle: multiple ? "选择本条已核对素材" : "选择本条单个素材")
        alert.addButton(withTitle: "手动选择其他素材")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { completion(nil); return }
            if response == .alertFirstButtonReturn {
                self.revalidateCurrentMedia(multiple: multiple, completion: completion)
            } else if response == .alertSecondButtonReturn {
                self.chooseManual(multiple: multiple, completion: completion)
            } else { self.finishSelection(nil, completion) }
        }
    }

    private func revalidateCurrentMedia(multiple: Bool, completion: @escaping ([URL]?) -> Void) {
        PublishingAPI.load(accountID: payload.account.id, draftID: payload.draft?.id) { [weak self] result in
            guard let self = self else { completion(nil); return }
            switch result {
            case .success(let current):
                guard self.matchesCurrent(current) else {
                    self.finishSelection(nil, completion)
                    self.showError("当前内容、素材或核对状态已变化。请回工作台重新检查后打开发布工作区。")
                    return
                }
                let urls = current.media.sorted(by: { $0.order < $1.order }).map { URL(fileURLWithPath: $0.path) }
                if multiple { self.finishSelection(urls, completion) }
                else { self.chooseOneCurrent(urls: urls, completion: completion) }
            case .failure(let error):
                self.finishSelection(nil, completion)
                self.showError(error.localizedDescription)
            }
        }
    }

    private func matchesCurrent(_ current: PublishingPayload) -> Bool {
        current.can_upload_current && current.draft?.fingerprint == payload.draft?.fingerprint
            && current.media.map(\.id) == payload.media.map(\.id)
            && current.media.allSatisfy(\.available) && permitted(webView.url)
    }

    private func chooseOneCurrent(urls: [URL], completion: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.title = "选择本条的一个素材"
        panel.message = "此平台入口每次只接受一个文件。按左侧编号选择；只有本条已核对的文件可继续。"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.movie, .image]
        panel.directoryURL = urls.first?.deletingLastPathComponent()
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { completion(nil); return }
            let chosen = panel.urls.filter { urls.contains($0) }
            guard response == .OK, chosen.count == 1 else {
                self.finishSelection(nil, completion)
                if response == .OK { self.showError("所选文件不属于本条已核对素材，请重新选择。") }
                return
            }
            // The picker may remain open while the user edits the draft or source.
            // Recheck at selection time, not only before displaying the picker.
            PublishingAPI.load(accountID: self.payload.account.id, draftID: self.payload.draft?.id) { [weak self] result in
                guard let self = self else { completion(nil); return }
                if case .success(let current) = result, self.matchesCurrent(current) {
                    self.finishSelection(chosen, completion)
                } else {
                    self.finishSelection(nil, completion)
                    self.showError("选择期间内容、素材或核对状态已变化，请回工作台重新检查。")
                }
            }
        }
    }

    private func chooseManual(multiple: Bool, completion: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.title = "选择要上传到 \(payload.platform.name) 的文件"
        panel.message = "文件将交给当前官方网页。请核对网页账号；手动选择不改变工作台里的审核和素材记录。"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = multiple
        panel.allowedContentTypes = [.movie, .image]
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { completion(nil); return }
            guard self.permitted(self.webView.url) else { self.finishSelection(nil, completion); return }
            self.finishSelection(response == .OK ? panel.urls : nil, completion)
        }
    }

    private func finishSelection(_ urls: [URL]?, _ completion: @escaping ([URL]?) -> Void) {
        selectingFiles = false
        completion(urls)
    }

    fileprivate func showStatus(_ message: String) {
        status.stringValue = "  " + message
        status.isHidden = false
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "发布工作区需要处理"
        alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: window)
    }
}
