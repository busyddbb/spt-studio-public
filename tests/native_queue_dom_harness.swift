import AppKit
import WebKit
import Foundation

@available(macOS 14.0, *)
final class Harness: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    private var loaded = false
    private let resource: String
    init(resource: String) {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 850), configuration: configuration)
        self.resource = resource
        super.init()
        webView.navigationDelegate = self
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded = true }
    func load(_ html: String) throws {
        loaded = false
        webView.loadHTMLString(html, baseURL: URL(string: "https://www.rednote.com/note-manager")!)
        let end = Date().addingTimeInterval(5)
        while !loaded && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
        precondition(loaded, "fixture did not load")
    }
    func evaluate(_ script: String) throws -> Any? {
        var value: Any?
        var failure: Error?
        let sem = DispatchSemaphore(value: 0)
        webView.evaluateJavaScript(script) { result, error in value = result; failure = error; sem.signal() }
        let end = Date().addingTimeInterval(5)
        while sem.wait(timeout: .now()) != .success && Date() < end {
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        }
        if let failure { throw failure }
        precondition(value != nil, "javascript evaluation timed out")
        return value
    }
    func snapshotPNG() throws -> Data {
        var image: NSImage?
        var failure: Error?
        let sem = DispatchSemaphore(value: 0)
        webView.takeSnapshot(with: nil) { value, error in image = value; failure = error; sem.signal() }
        let end = Date().addingTimeInterval(5)
        while sem.wait(timeout: .now()) != .success && Date() < end {
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        }
        if let failure { throw failure }
        guard let image, let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
              let data = rep.representation(using: .png, properties: [:]), !data.isEmpty else {
            throw NSError(domain: "Harness", code: 1, userInfo: [NSLocalizedDescriptionKey: "empty WKWebView snapshot"])
        }
        return data
    }
    func step(_ args: [String: Any]) throws -> [String: Any] {
        let data = try JSONSerialization.data(withJSONObject: args)
        let json = String(data: data, encoding: .utf8)!
        return (try evaluate(resource + "(" + json + ")")) as? [String: Any] ?? [:]
    }
    func navigate(_ path: String) throws {
        let arrayJSON = String(data: try JSONSerialization.data(withJSONObject: [path]), encoding: .utf8)!
        let quoted = String(arrayJSON.dropFirst().dropLast())
        _ = try evaluate("history.replaceState({}, '', " + quoted + "); true")
    }
}

@available(macOS 14.0, *)
func runHarness() throws {
    NSApplication.shared.setActivationPolicy(.prohibited)
    let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
    let resource = try String(contentsOf: root.appendingPathComponent("native/PublishingQueueDOM.js"), encoding: .utf8)
    let png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    let names = (1...6).map { String(format: "%02d.png", $0) }
    func fixture(topics: String = "", plain: String = "", card: String = "", profileLink: Bool = true, author: String = "") -> String {
        let media = names.map { "<img data-filename=\"\($0)\" src=\"data:image/png;base64,\(png)\"/>" }.joined()
        let accountLink = profileLink ? "<a href=\"/profile/0123456789abcdef01234567\">账号</a>" : ""
        return """
        <style>html,body{display:block;width:1200px;height:850px} .upload-list{display:block}</style>
        <header><span data-testid="account">示例创作者</span>\(accountLink)</header>
        <input placeholder="填写标题会有更多赞哦" value="测试标题">
        <div class="ProseMirror" contenteditable="true">正文\(plain)\(topics)</div>
        <label>允许正文复制<input type="checkbox"></label><label>定时发布<input type="checkbox"></label>
        <button>公开可见</button><div class="upload-list">\(media)</div>
        <input type="file" id="chooser"><button>发布</button>\(card)\(author)
        <button>全部笔记</button><button>草稿箱</button><div role="status">暂无内容</div>
        """
    }
    func installFiles(_ h: Harness) throws {
        _ = try h.evaluate("(()=>{const dt=new DataTransfer();const b=Uint8Array.from(atob('\(png)'),c=>c.charCodeAt(0));for(let i=1;i<=6;i++)dt.items.add(new File([b],String(i).padStart(2,'0')+'.png',{type:'image/png'}));document.querySelector('#chooser').files=dt.files;return true})()")
    }
    let id = "0123456789abcdef01234567"
    func options(_ topics: [String] = [], allowCopy: Bool = false) -> [String: Any] {
        ["topics": topics, "expected_profile_id": id, "expected_name": "示例创作者", "allow_body_copy": allowCopy, "visibility": "public", "duplicate_checked": true]
    }
    func args(_ opts: [String: Any], phase: String, title: String = "测试标题", body: String = "正文") -> [String: Any] {
        ["options": opts, "title": title, "body": body, "mediaNames": names, "phase": phase]
    }
    let h = Harness(resource: resource)
    try h.load(fixture()); try installFiles(h)
    let screenshot = try h.snapshotPNG()
    precondition(!screenshot.isEmpty, "invisible WKWebView must still provide non-empty PNG evidence")
    let zero = try h.step(args(options(), phase: "preflight"))
    precondition(zero["status"] as? String == "proof", "zero-topic preflight should produce proof: \(zero)")
    try h.load(fixture(plain: " #爸爸带娃 #带娃日常")); try installFiles(h)
    let plain = try h.step(args(options(["爸爸带娃", "带娃日常", "亲子漫画", "亲子互动", "户外亲子"]), phase: "preflight"))
    precondition(plain["status"] as? String != "proof", "plaintext topics must not produce proof")
    let fiveTopics = ["爸爸带娃", "带娃日常", "亲子漫画", "亲子互动", "户外亲子"]
    let structured = fiveTopics.map { "<span contenteditable=\"false\" data-type=\"topic\" data-topic=\"\($0)\">#\($0)[话题]#</span>" }.joined()
    try h.load(fixture(topics: structured)); try installFiles(h)
    let five = try h.step(args(options(fiveTopics), phase: "preflight"))
    precondition(five["status"] as? String == "proof", "five structured topics should produce proof: \(five)")
    var wrong = options(); wrong["expected_profile_id"] = "fedcba9876543210fedcba98"
    let bad = try h.step(args(wrong, phase: "preflight"))
    precondition(bad["status"] as? String == "attention", "wrong identity must stop")
    try h.load(fixture(topics: structured)); try installFiles(h)
    let toggled = try h.step(args(options(fiveTopics, allowCopy: true), phase: "preflight"))
    precondition(toggled["status"] as? String == "wait", "copy setting should be changed before proof")
    let toggledProof = try h.step(args(options(fiveTopics, allowCopy: true), phase: "preflight"))
    precondition(toggledProof["status"] as? String == "proof", "copy setting readback should produce proof")
    try h.load(fixture()); try installFiles(h)
    let click = try h.step(args(options(), phase: "click"))
    precondition(click["status"] as? String == "clicked", "unique publish should click")
    let repeatClick = try h.step(args(options(), phase: "click"))
    precondition(repeatClick["status"] as? String == "attention", "publish must be single click")
    let duplicateCard = "<article class=\"note-card\"><a href=\"/publish/update?id=0123456789abcdef01234567\">测试标题</a></article>"
    try h.load(fixture(card: duplicateCard))
    let duplicate = try h.step(args(options(), phase: "duplicate"))
    precondition(duplicate["status"] as? String == "duplicate", "same-title duplicate must stop")
    try h.load(fixture())
    let unknown = try h.step(args(options(), phase: "result"))
    precondition(unknown["status"] as? String != "result" && unknown["status"] as? String != "result_card", "unknown result must not be published")

    // Identity fallback: manager header has only the account name; the first
    // owned note edit URL supplies the note id, then the public author is checked.
    let identityCard = "<article class=\"note-card\"><a href=\"/publish/update?id=0123456789abcdef01234567\">旧笔记</a></article>"
    try h.load(fixture(card: identityCard, profileLink: false))
    let identityNote = try h.step(args(options(), phase: "duplicate", title: "测试标题"))
    precondition(identityNote["status"] as? String == "identity_note" && identityNote["note_id"] as? String == id, "missing manager profile link should yield identity_note: \(identityNote)")
    let authorMarkup = "<div class=\"author-container\"><a href=\"/user/profile/0123456789abcdef01234567\">主页</a><span>示例创作者</span></div>"
    try h.load(fixture(author: authorMarkup))
    let verifiedIdentity = try h.step(args(options(), phase: "identity_verify"))
    precondition(verifiedIdentity["status"] as? String == "identity_verified" && verifiedIdentity["account_profile_id"] as? String == id, "matching public author should verify identity: \(verifiedIdentity)")
    let wrongAuthor = "<div class=\"author-container\"><a href=\"/user/profile/fedcba9876543210fedcba98\">主页</a><span>示例创作者</span></div>"
    try h.load(fixture(author: wrongAuthor))
    let rejectedIdentity = try h.step(args(options(), phase: "identity_verify"))
    precondition(rejectedIdentity["status"] as? String == "attention", "wrong public author must stop")

    // Current manager: unlabelled div cards, note id only inside data-impression JSON.
    let plainCards = "<div class=\"list\"><div class=\"x1\" data-impression='{\"noteTarget\":{\"value\":{\"noteId\":\"\(id)\"}}}'><div><img src=\"data:image/png;base64,\(png)\"><span>旧笔记一</span></div><div><span>发布于 2026年10月20日 12:00</span></div></div><div class=\"x1\"><span>旧笔记二</span><span>发布于 2026年10月18日 09:30</span></div></div>"
    try h.load(fixture(card: plainCards, profileLink: false))
    let plainNote = try h.step(args(options(), phase: "duplicate", title: "测试标题"))
    precondition(plainNote["status"] as? String == "identity_note" && plainNote["note_id"] as? String == id, "unlabelled cards should yield identity_note: \(plainNote)")
    let timeOnly = "<div class=\"list\"><div class=\"x2\"><a href=\"/publish/update?id=\(id)\">编辑</a><span>旧笔记</span><span>2026-10-20 12:00</span></div><div class=\"x2\"><span>另一篇</span><span>2026-10-19 12:00</span></div></div>"
    try h.load(fixture(card: timeOnly, profileLink: false))
    let timeNote = try h.step(args(options(), phase: "duplicate", title: "测试标题"))
    precondition(timeNote["status"] as? String == "identity_note" && timeNote["note_id"] as? String == id, "time-anchored cards should yield identity_note: \(timeNote)")
    // A list that has not loaded yet must wait (switching to 全部 first), never fail at once.
    try h.load(fixture(profileLink: false))
    let loading1 = try h.step(args(options(), phase: "duplicate", title: "测试标题"))
    let loading2 = try h.step(args(options(), phase: "duplicate", title: "测试标题"))
    precondition(loading1["status"] as? String == "wait" && loading2["status"] as? String == "wait", "unloaded list must wait: \(loading1) \(loading2)")

    // Public note pages redirect to /404 now: fall back to the public profile page.
    try h.load(fixture()); try h.navigate("/404/sec_abc?error_code=300031")
    let toProfile = try h.step(args(options(), phase: "identity_verify"))
    precondition(toProfile["status"] as? String == "identity_profile" && (toProfile["url"] as? String) == "https://www.rednote.com/user/profile/\(id)", "dead note page must switch to profile: \(toProfile)")
    let profileMarkup = "<div class=\"user-info\"><div class=\"user-name\">示例创作者</div><button>编辑资料</button></div>"
    try h.load(fixture(author: profileMarkup)); try h.navigate("/user/profile/\(id)")
    let profileOK = try h.step(args(options(), phase: "identity_verify"))
    precondition(profileOK["status"] as? String == "identity_verified" && profileOK["basis"] as? String == "profile_owner", "own profile must verify identity: \(profileOK)")
    let otherProfile = "<div class=\"user-info\"><div class=\"user-name\">别人</div></div>"
    try h.load(fixture(author: otherProfile)); try h.navigate("/user/profile/\(id)")
    let profileWait = try h.step(args(options(), phase: "identity_verify"))
    precondition(profileWait["status"] as? String == "wait", "other name on profile must not verify: \(profileWait)")

    // The platform's submit bar: a custom element with a closed shadow root kept as _sr.
    let component = "<script>customElements.define('xhs-publish-btn', class extends HTMLElement { connectedCallback() { this._sr = this.attachShadow({mode: 'closed'}); this._sr.innerHTML = '<button id=\"s\">' + this.getAttribute('submit-text') + '</button><button>' + this.getAttribute('save-text') + '</button>'; this._sr.getElementById('s').addEventListener('click', () => { window.__sptHit = (window.__sptHit || 0) + 1; }); } });</script><xhs-publish-btn submit-text=\"发布\" save-text=\"暂存离开\" submit-disabled=\"false\" submit-loading=\"false\"></xhs-publish-btn>"
    try h.load(fixture(card: component).replacing("<button>发布</button>", with: "")); try installFiles(h)
    let viaComponent = try h.step(args(options(), phase: "click"))
    let hits = try h.evaluate("window.__sptHit") as? Int
    precondition(viaComponent["status"] as? String == "clicked" && hits == 1, "component publish button must be clicked once: \(viaComponent) hits=\(String(describing: hits))")
    let loadingBar = component.replacingOccurrences(of: "submit-loading=\"false\"", with: "submit-loading=\"true\"")
    try h.load(fixture(card: loadingBar).replacing("<button>发布</button>", with: "")); try installFiles(h)
    let waiting = try h.step(args(options(), phase: "click"))
    precondition(waiting["status"] as? String == "wait", "loading submit bar must wait: \(waiting)")

    // Positive result chain: exact selected tab + unique title card + edit URL,
    // then the same note is verified from its edit page and full content.
    let resultCard = "<div role=\"tab\" aria-selected=\"true\">已发布</div><article class=\"note-card\"><a href=\"/publish/update?id=0123456789abcdef01234567\">测试标题</a></article>"
    try h.load(fixture(topics: structured, card: resultCard)); try installFiles(h)
    let resultCardStep = try h.step(args(options(fiveTopics), phase: "result"))
    precondition(resultCardStep["status"] as? String == "result_card", "exact result card should produce result_card: \(resultCardStep)")
    let record = resultCardStep
    try h.navigate("/publish/update?id=0123456789abcdef01234567")
    var verifyOptions = options(fiveTopics)
    verifyOptions["result_record"] = record
    let verified = try h.step(args(verifyOptions, phase: "result_verify"))
    precondition(verified["status"] as? String == "result" && verified["note_id"] as? String == id && (verified["evidence"] as? [String: Any])?["content_verified"] as? Bool == true, "edit-page content verification should pass: \(verified)")
    try h.navigate("/publish/update?id=fedcba9876543210fedcba98")
    let wrongResultID = try h.step(args(verifyOptions, phase: "result_verify"))
    precondition(wrongResultID["status"] as? String == "attention", "wrong result note id must stop")
    try h.navigate("/publish/update?id=0123456789abcdef01234567")
    let wrongBody = try h.step(args(verifyOptions, phase: "result_verify", body: "错误正文"))
    precondition(wrongBody["status"] as? String == "attention", "edit-page body mismatch must stop")
    print("native queue DOM harness: ok (8 cases + positive result chain + identity fallback + unlabelled cards + list wait + profile identity + submit component + snapshot)")
}

if #available(macOS 14.0, *) { try runHarness() }
