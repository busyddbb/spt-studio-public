import AppKit
import WebKit

/// SPT 读数据. The local server holds read requests (the 数据 page button,
/// `spt metrics capture`, or its own schedule); this coordinator claims them and,
/// for every account that has logged in inside SPT on a platform with a reader
/// (小红书, TikTok, Instagram and Facebook through Meta Business Suite), opens that
/// platform's own list of published posts with the account's saved session, reads the
/// list as shown, and for 小红书 the follower count on the public profile. What the
/// pages showed goes back to the server, which matches posts to works and appends
/// to their 数据/表现.csv.
///
/// Read-only on the platform: a few page loads and some scrolling. Nothing is typed;
/// the only clicks open a post's own insights page and pick its Instagram tab (Meta
/// lists a crossposted reel's Facebook figures). No cookies, tokens or passwords leave WebKit.
@available(macOS 14.0, *)
final class MetricsReaderCoordinator {
    static let platforms = ["xiaohongshu", "tiktok", "instagram", "facebook"]
    private var timer: Timer?
    private var busy = false
    private var reader: PlatformMetricsReader?

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in self?.poll() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in self?.poll() }
    }

    private func poll() {
        guard !busy else { return }
        busy = true
        MetricsReaderAPI.post("claim", ["auto": true]) { [weak self] result in
            guard let self else { return }
            guard let task = result?["task"] as? [String: Any], let id = task["id"] as? String else {
                self.busy = false
                return
            }
            self.run(id: id)
        }
    }

    private func run(id: String) {
        MetricsReaderAPI.get("/api/publishing") { [weak self] result in
            guard let self else { return }
            let accounts = (result?["accounts"] as? [[String: Any]] ?? []).filter {
                Self.platforms.contains($0["platform"] as? String ?? "") && $0["session_saved"] as? Bool == true
                    && UUID(uuidString: $0["profile_id"] as? String ?? "") != nil
            }
            self.read(id: id, accounts: accounts, index: 0)
        }
    }

    private func read(id: String, accounts: [[String: Any]], index: Int) {
        guard index < accounts.count else {
            reader = nil
            MetricsReaderAPI.post("finish", ["id": id, "reason": "还没有在 SPT 里登录过账号：先在 发布 → 平台入口 打开平台登录一次"]) { [weak self] _ in
                self?.busy = false
            }
            return
        }
        let account = accounts[index]
        let platform = account["platform"] as? String ?? "xiaohongshu"
        // Instagram and Facebook share one Meta Business Suite login: when this account's own
        // pane never signed in, the client's other Meta account's session is tried next.
        var profiles = [UUID(uuidString: account["profile_id"] as? String ?? "")!]
        if platform == "instagram" || platform == "facebook" {
            profiles += accounts.filter {
                ["instagram", "facebook"].contains($0["platform"] as? String ?? "")
                    && $0["brand"] as? String == account["brand"] as? String
                    && $0["profile_id"] as? String != account["profile_id"] as? String
            }.compactMap { UUID(uuidString: $0["profile_id"] as? String ?? "") }
        }
        read(id: id, accounts: accounts, index: index, account: account, platform: platform, profiles: profiles)
    }

    private func read(id: String, accounts: [[String: Any]], index: Int, account: [String: Any],
                      platform: String, profiles: [UUID]) {
        let identity: [String: Any] = ["id": account["id"] ?? "", "name": account["name"] ?? "",
                                       "brand": account["brand"] ?? "", "platform": platform,
                                       "handle": account["handle"] ?? ""]
        reader = PlatformMetricsReader(platform: platform, profile: profiles[0], handle: account["handle"] as? String) { [weak self] outcome in
            let rest = Array(profiles.dropFirst())
            if outcome["status"] as? String == "login", !rest.isEmpty {
                self?.read(id: id, accounts: accounts, index: index, account: account, platform: platform, profiles: rest)
                return
            }
            var report = outcome
            report["id"] = id
            report["account"] = identity
            MetricsReaderAPI.post("result", report) { _ in
                self?.read(id: id, accounts: accounts, index: index + 1)
            }
        }
        reader?.begin()
    }
}

@available(macOS 14.0, *)
private enum MetricsReaderAPI {
    static let base = "http://127.0.0.1:8766"

    static func get(_ path: String, completion: @escaping ([String: Any]?) -> Void) {
        var request = URLRequest(url: URL(string: base + path)!)
        request.timeoutInterval = 15
        perform(request, completion: completion)
    }

    static func post(_ action: String, _ body: [String: Any], completion: @escaping ([String: Any]?) -> Void) {
        var request = URLRequest(url: URL(string: base + "/api/spt/metrics/capture/" + action)!)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        perform(request, completion: completion)
    }

    private static func perform(_ request: URLRequest, completion: @escaping ([String: Any]?) -> Void) {
        URLSession.shared.dataTask(with: request) { data, response, _ in
            var value: [String: Any]?
            if let data, let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) {
                value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            }
            DispatchQueue.main.async { completion(value) }
        }.resume()
    }
}

/// What one platform's reader opens and may visit.
@available(macOS 14.0, *)
struct ReaderPlatform {
    let code: String            // the page script's platform argument
    let start: URL              // the first page; the script may ask to navigate on from there
    let allowed: [String]       // main-frame hosts the reader may load
    let readsProfile: Bool      // 小红书 only: the public profile for followers

    static func named(_ platform: String) -> ReaderPlatform {
        switch platform {
        case "tiktok":
            return ReaderPlatform(code: "tiktok", start: URL(string: "https://www.tiktok.com/tiktokstudio/content")!,
                                  allowed: ["tiktok.com", "tiktokcdn.com", "tiktokv.com", "ttwstatic.com", "byteoversea.com"], readsProfile: false)
        case "instagram", "facebook":
            return ReaderPlatform(code: platform, start: URL(string: "https://business.facebook.com/latest/home")!,
                                  allowed: ["facebook.com", "fbcdn.net", "fbsbx.com", "instagram.com", "meta.com"], readsProfile: false)
        default:
            return ReaderPlatform(code: "rednote", start: URL(string: "https://creator.rednote.com/new/note-manager")!,
                                  allowed: ["rednote.com", "xiaohongshu.com", "xhscdn.com", "xhslink.com"], readsProfile: true)
        }
    }
}

/// Reads one account: the platform's list of published posts (and the header's account
/// name), then for 小红书 the public profile (followers). Finishes exactly once with what it saw.
@available(macOS 14.0, *)
final class PlatformMetricsReader: NSObject, WKNavigationDelegate, WKUIDelegate {
    private let platform: ReaderPlatform
    private let accountPlatform: String
    private let profile: UUID
    private let profileURL: URL?
    private let completion: ([String: Any]) -> Void
    private let webView: WKWebView
    private var timer: Timer?
    private var phase = "notes"
    private var deadline = Date()
    private var result: [String: Any] = [:]
    private var finished = false
    private var opened = false
    private var navigations = 0
    private var lastWait = ""

    init(platform accountPlatform: String, profile: UUID, handle: String?, completion: @escaping ([String: Any]) -> Void) {
        self.accountPlatform = accountPlatform
        self.platform = ReaderPlatform.named(accountPlatform)
        self.profile = profile
        self.completion = completion
        if self.platform.readsProfile, let handle, let range = handle.range(of: "[0-9a-f]{24}", options: .regularExpression) {
            profileURL = URL(string: "https://www.rednote.com/user/profile/" + handle[range])
        } else { profileURL = nil }
        let configuration = WKWebViewConfiguration()
        if accountPlatform == "xiaohongshu" {
            RednoteBrowserIdentity.apply(to: configuration)
            configuration.websiteDataStore = RednoteSessionVault.shared.dataStore(profile: profile)
        } else {
            // The same store the account's publishing pane logged in with (PublishingWorkspace.swift).
            configuration.websiteDataStore = WKWebsiteDataStore(forIdentifier: profile)
        }
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = [.audio, .video]
        // Meta's tables only render the columns on screen: a wide frame shows them all at once.
        let width: CGFloat = accountPlatform == "instagram" || accountPlatform == "facebook" ? 3000 : 1280
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: 900), configuration: configuration)
        super.init()
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsLinkPreview = false
    }

    func begin() {
        guard accountPlatform == "xiaohongshu" else {
            open(platform.start, phase: "notes", seconds: 90)
            return
        }
        // Restoring the session can wait on a macOS keychain prompt; never wait forever.
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
            guard let self, !self.opened else { return }
            self.finish(["status": "attention", "reason": "等钥匙串放行：在弹出的「钥匙串」窗口点「始终允许」后再读一次"])
        }
        RednoteSessionVault.shared.prepare(profile: profile, onError: { _ in }, completion: { [weak self] _ in
            guard let self, !self.finished else { return }
            self.open(self.platform.start, phase: "notes", seconds: 75)
        })
    }

    private func open(_ url: URL, phase: String, seconds: TimeInterval) {
        opened = true
        self.phase = phase
        deadline = Date().addingTimeInterval(seconds)
        webView.load(URLRequest(url: url))
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in self?.step() }
    }

    private func step() {
        guard !finished else { return }
        if Date() > deadline {
            if phase == "profile" { finish(result) }   // followers are a bonus; the notes are in
            else {
                let page = webView.url?.absoluteString ?? ""
                finish(["status": "attention", "reason": "列表页面没有读出来：" + lastWait + "（" + page.prefix(120) + "）"])
            }
            return
        }
        webView.evaluateJavaScript(Self.script(phase: phase, platform: platform.code)) { [weak self] value, _ in
            guard let self, !self.finished, let value = value as? [String: Any] else { return }
            switch value["status"] as? String {
            case "login":
                if self.phase == "profile" { self.finish(self.result) }
                else { self.finish(["status": "login"]) }
            case "navigate":
                // The script found where the list lives (Meta needs the asset ids in the address).
                guard self.navigations < 3, let text = value["url"] as? String, let url = URL(string: text), self.permitted(url) else {
                    self.finish(["status": "attention", "reason": "页面要跳到不允许的地址：" + String(describing: value["url"] ?? "")])
                    return
                }
                self.navigations += 1
                self.open(url, phase: "notes", seconds: 75)
            case "wait":
                self.lastWait = value["reason"] as? String ?? ""
                // Walking posts one by one (Meta) is slow but moving: each finished post buys more time.
                if self.lastWait.hasPrefix("读完一篇") || self.lastWait.hasPrefix("打开帖子详情") {
                    self.deadline = max(self.deadline, Date().addingTimeInterval(45))
                }
            case "done" where self.phase == "notes":
                self.result = ["status": "done", "header": value["header"] ?? [], "notes": value["notes"] ?? [],
                               "page": value["page"] ?? "", "filter": value["filter"] ?? "",
                               "observed_at": ISO8601DateFormatter().string(from: Date())]
                if let url = self.profileURL { self.open(url, phase: "profile", seconds: 30) }
                else { self.finish(self.result) }
            case "done":
                self.result["profile"] = ["followers": value["followers"] ?? NSNull()]
                self.finish(self.result)
            case "attention":
                self.finish(["status": "attention", "reason": value["reason"] ?? "页面看不懂"])
            default: break
            }
        }
    }

    private func finish(_ outcome: [String: Any]) {
        guard !finished else { return }
        finished = true
        timer?.invalidate()
        timer = nil
        webView.stopLoading()
        completion(outcome)
    }

    private static func script(phase: String, platform: String) -> String {
        // The workspace copy of the page script, when present, wins over the bundled one, so a page fix needs no rebuild.
        let root = Bundle.main.object(forInfoDictionaryKey: "MediaDeskWorkspaceRoot") as? String
        let onDisk = root.map { URL(fileURLWithPath: $0).appendingPathComponent("native/MetricsReaderDOM.js") }
        let resource = onDisk.flatMap { FileManager.default.isReadableFile(atPath: $0.path) ? $0 : nil }
            ?? Bundle.main.url(forResource: "MetricsReaderDOM", withExtension: "js")
        guard let resource,
              let source = try? String(contentsOf: resource, encoding: .utf8),
              let data = try? JSONSerialization.data(withJSONObject: [
                "phase": phase, "platform": platform, "days": 14, "now": Date().timeIntervalSince1970 * 1000]),
              let arguments = String(data: data, encoding: .utf8) else {
            return "({status:'attention',reason:'读数据脚本不可用'})"
        }
        return "(" + source + ")(" + arguments + ")"
    }

    private func permitted(_ url: URL?) -> Bool {
        guard let url, url.scheme == "https", url.user == nil, url.password == nil,
              let host = url.host?.lowercased() else { return false }
        return platform.allowed.contains { host == $0 || host.hasSuffix("." + $0) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.targetFrame?.isMainFrame == false {
            decisionHandler(action.request.url?.scheme == "https" ? .allow : .cancel)
        } else { decisionHandler(permitted(action.request.url) ? .allow : .cancel) }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        nil   // no pop-ups
    }
}
