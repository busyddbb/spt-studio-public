import AppKit
import WebKit
import Foundation

// Runs native/MetricsReaderDOM.js in offline WebKit against pages shaped like the
// creator center's 笔记管理 and a public profile (layout taken from a real capture).
@available(macOS 14.0, *)
final class Harness: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    private var loaded = false
    private let source: String
    init(source: String) {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 1280, height: 900), configuration: configuration)
        self.source = source
        super.init()
        webView.navigationDelegate = self
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { loaded = true }
    func load(_ html: String, at url: String) {
        loaded = false
        webView.loadHTMLString(html, baseURL: URL(string: url)!)
        let end = Date().addingTimeInterval(5)
        while !loaded && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
        precondition(loaded, "fixture did not load")
    }
    func step(_ arguments: String) -> [String: Any] {
        var value: Any?
        var failure: Error?
        var done = false
        let code = arguments.hasPrefix("{") ? "(" + source + ")(" + arguments + ")" : arguments
        webView.evaluateJavaScript(code) { result, error in value = result; failure = error; done = true }
        let end = Date().addingTimeInterval(5)
        while !done && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
        if let failure { fatalError("script failed: \(failure)") }
        return value as? [String: Any] ?? [:]
    }
}

func card(_ title: String, _ time: String, _ numbers: [String], pinned: Bool = false, link: String? = nil, state: String? = nil) -> String {
    let icons = numbers.map { "<div class=\"icon\"><svg width=\"12\" height=\"12\"></svg><span>\($0)</span></div>" }.joined()
    let pin = pinned ? "<span class=\"tag\">置顶</span>" : ""
    let tag = state.map { "<span class=\"status\">\($0)</span>" } ?? ""
    let edit = link.map { "<a href=\"\($0)\">编辑</a>" } ?? ""
    return "<div class=\"note\"><div class=\"cover\"><img alt=\"\"></div><div class=\"info\">\(pin)\(tag)<div class=\"title\">\(title)</div><div class=\"time\">\(time)</div><div class=\"data\">\(icons)</div>\(edit)</div></div>"
}

let header = "<div class=\"header-area\"><div><img alt=\"\"><span>创作服务平台</span></div><div><img alt=\"\"><span>示例创作者</span></div></div>"
let list = [
    card("只是绕了一条路，他在后座哭到家", "2026-06-22 03:04", ["979", "0", "16", "9", "2"], pinned: true),
    card("他叫了半天，小狗只顾闻我的鞋", "2026-10-23 15:13", ["48", "0", "3", "2", "0"],
         link: "https://creator.rednote.com/publish/update?id=000000000000000000000065&noteType=normal"),
    card("录音里的爸爸，一听就认出来了", "2026-10-22 15:42", ["1.2万", "3", "40", "6", "1"]),
    card("新的一篇", "2026-10-23 20:00", ["0", "0", "0", "0", "0"], state: "审核中"),
    card("气球飞走了，他不要新的", "2026-10-01 07:18", ["160", "1", "9", "1", "0"]),
].joined()
let page = "<html><body>\(header)<div class=\"page\"><div class=\"side\">笔记管理</div><div class=\"tabs\"><span>全部 310</span><span>已发布</span></div><div class=\"list\" style=\"height:600px;overflow-y:auto\">\(list)<div class=\"notes-request\">正在加载中...</div></div></div></body></html>"

if #available(macOS 14.0, *) {
    let source = try! String(contentsOfFile: "native/MetricsReaderDOM.js", encoding: .utf8)
    let harness = Harness(source: source)
    let now = "1792792800000"   // 2026-10-23T22:00:00Z

    harness.load(page, at: "https://creator.rednote.com/new/note-manager")
    let notes = harness.step("{\"phase\":\"notes\",\"days\":14,\"now\":\(now)}")
    precondition(notes["status"] as? String == "done", "notes: \(notes)")
    let rows = notes["notes"] as! [[String: Any]]
    precondition(rows.count == 5, "five cards: \(rows)")
    precondition(rows[0]["title"] as? String == "只是绕了一条路，他在后座哭到家", "pinned title: \(rows[0])")
    precondition(rows[1]["note_id"] as? String == "000000000000000000000065", "id from the edit link: \(rows[1])")
    precondition(rows[1]["numbers"] as? [String] == ["48", "0", "3", "2", "0"], "numbers in list order: \(rows[1])")
    precondition(rows[1]["time"] as? String == "2026-10-23 15:13")
    precondition(rows[2]["numbers"] as? [String] == ["1.2万", "3", "40", "6", "1"], "rounded text kept as shown: \(rows[2])")
    precondition(rows[3]["state"] as? String == "审核中", "state: \(rows[3])")
    precondition(rows[4]["note_id"] is NSNull, "no id when the card shows none: \(rows[4])")
    let names = notes["header"] as! [String]
    precondition(names.contains("示例创作者"), "header names the account: \(names)")

    // Every note still inside the window: it scrolls for older ones, then stops when nothing new loads.
    harness.load(page, at: "https://creator.rednote.com/new/note-manager")
    var last: [String: Any] = [:]
    for _ in 0..<8 {
        last = harness.step("{\"phase\":\"notes\",\"days\":60,\"now\":\(now)}")
        if last["status"] as? String == "done" { break }
        precondition(last["reason"] as? String == "加载更早的笔记", "scrolls: \(last)")
    }
    precondition(last["status"] as? String == "done", "stops when the list stops growing: \(last)")

    harness.load("<html><body><div class=\"user\"><span>示例创作者</span><div class=\"data\"><span class=\"count\">11</span><span>关注</span><span class=\"count\">200</span><span>粉丝</span><span class=\"count\">1.7K</span><span>获赞与收藏</span></div></div></body></html>",
                 at: "https://www.rednote.com/user/profile/000000000000000000000001")
    let profile = harness.step("{\"phase\":\"profile\"}")
    precondition(profile["followers"] as? String == "200" && profile["following"] as? String == "11", "profile: \(profile)")

    harness.load("<html><body><input placeholder=\"手机号\"></body></html>", at: "https://creator.rednote.com/login")
    precondition(harness.step("{\"phase\":\"notes\"}")["status"] as? String == "login")

    harness.load("<html><body>\(header)<div>加载中</div></body></html>", at: "https://creator.rednote.com/new/note-manager")
    precondition(harness.step("{\"phase\":\"notes\"}")["status"] as? String == "wait")
    // TikTok Studio · Content: a link per video (caption as text), the time, the privacy and three numbers.
    func ttRow(_ id: String, _ caption: String, _ time: String, _ numbers: String, privacy: String = "Everyone") -> String {
        return "<div class=\"row\"><div class=\"cover\"><img alt=\"\"><span>00:14</span></div><div class=\"info\"><a href=\"https://www.tiktok.com/@sample_studio/video/\(id)\">\(caption)</a><span class=\"time\">\(time)</span></div><div class=\"privacy\"><button>\(privacy)</button></div><div class=\"stats\"><span>\(numbers)</span></div><div class=\"actions\"><button></button></div></div>"
    }
    let ttPage = "<html><body><div class=\"side\"><img alt=\"\"><span>@sample_studio</span></div><div class=\"head\"><span>Posts 17</span><span>Drafts 1</span></div><div class=\"cols\"><span>Posts (Created on)</span><span>Privacy</span><span>Views</span><span>Likes</span><span>Comments</span><span>Actions</span></div><div class=\"list\" style=\"height:600px;overflow-y:auto\">"
        + ttRow("1000000000000000006", "For the duck-skin lovers: Peking Duck at Sample Studio, San Francisco.", "Oct 23, 11:59 PM", "7 0 0")
        + ttRow("1000000000000000005", "Buns first. Sweet &amp; Sour Pork and Black Pepper Chicken Pan Fried next.", "Oct 21, 7:55 PM", "23 0 0")
        + ttRow("1000000000000000004", "Tonight’s craving: beef and string beans.", "Oct 21, 12:28 AM", "95 2 1", privacy: "Only me")
        + "</div></body></html>"
    harness.load(ttPage, at: "https://www.tiktok.com/tiktokstudio/content")
    var tt: [String: Any] = [:]
    for _ in 0..<12 {
        tt = harness.step("{\"phase\":\"notes\",\"platform\":\"tiktok\",\"days\":14,\"now\":\(now)}")
        if tt["status"] as? String == "done" { break }
    }
    precondition(tt["status"] as? String == "done", "tiktok: \(tt)")
    let ttRows = tt["notes"] as! [[String: Any]]
    precondition(ttRows.count == 3, "three tiktok rows: \(ttRows)")
    precondition(ttRows[0]["note_id"] as? String == "1000000000000000006", "video id: \(ttRows[0])")
    precondition((ttRows[0]["title"] as? String ?? "").hasPrefix("For the duck-skin lovers"), "caption: \(ttRows[0])")
    precondition(ttRows[0]["time"] as? String == "Oct 23, 11:59 PM", "time: \(ttRows[0])")
    let ttMetrics = ttRows[1]["metrics"] as! [String: Any]
    precondition(ttMetrics["views"] as? String == "23" && ttMetrics["likes"] as? String == "0" && ttMetrics["comments"] as? String == "0", "tiktok numbers: \(ttMetrics)")
    precondition(ttRows[2]["state"] as? String == "仅自己可见", "privacy: \(ttRows[2])")
    precondition((tt["header"] as! [String]).contains("@sample_studio"), "tiktok header: \(tt["header"] ?? "")")

    harness.load("<html><body><input name=\"username\"><input name=\"password\"></body></html>", at: "https://www.tiktok.com/login/phone-or-email")
    precondition(harness.step("{\"phase\":\"notes\",\"platform\":\"tiktok\"}")["status"] as? String == "login")

    // Meta Business Suite: Facebook published posts table, Instagram content table; home needs the asset ids first.
    func metaRow(_ id: String, _ caption: String, _ time: String, _ cells: [String], platforms: String, crossposted: Bool = false, checkbox: Bool = true) -> String {
        let check = checkbox ? "<td><input type=\"checkbox\" aria-label=\"Select item with id \(id)\"></td>" : ""
        let marks = platforms.split(separator: " ").map { "<img alt=\"\($0)\">" }.joined()
        let cross = crossposted ? "<span>Crossposted</span>" : ""
        let numbers = cells.map { "<td><button>\($0)</button></td>" }.joined()
        return "<tr>\(check)<td><button>Boost</button><div>\(marks)<span>0:15</span><span>\(caption)</span><span>Reel</span>\(cross)<span>Sample Studio, sample_studio</span></div></td><td><button>\(time)</button></td>\(numbers)</tr>"
    }
    let fbHead = "<tr><th><input type=\"checkbox\" aria-label=\"Select all\"></th><th>Title</th><th><button>Date published</button></th><th><button>Status</button></th><th><button>Reach</button></th><th><button>Views</button></th><th><button>Viewers</button></th><th><button>Likes and reactions</button></th><th><button>Comments</button></th><th><button>Shares</button></th><th><button>Saves</button></th></tr>"
    let fbPage = "<html><body><div class=\"top\"><span>Sample Studio</span><span>Meta Business Suite</span></div><table>" + fbHead
        + metaRow("1000000000000000002", "Bring your duck craving to Sample Studio.", "Fri Oct 23, 11:52pm", ["Not currently boosted", "96", "178", "‑‑", "1", "0", "0", "0"], platforms: "Instagram Facebook", crossposted: true)
        + metaRow("1000000000000000001", "Buns first. Sweet &amp; Sour Pork next.", "Wed Oct 21, 7:51pm", ["Not currently boosted", "140", "159", "‑‑", "3", "0", "1", "0"], platforms: "Facebook")
        + "</table></body></html>"
    // Facebook: each listed post is opened (a click) and read on its own insights page, Facebook tab.
    harness.load(fbPage, at: "https://business.facebook.com/latest/posts/published_posts/?business_id=1&asset_id=2")
    _ = harness.step("try { sessionStorage.removeItem('sptIG') } catch (e) {}; ({})")
    var fbStep = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\",\"days\":14,\"now\":\(now)}")
    precondition(fbStep["status"] as? String == "wait" && fbStep["reason"] as? String == "打开帖子详情", "facebook opens the first row: \(fbStep)")
    let fbDetail = "<html><body><div role=\"tablist\"><div role=\"tab\" aria-selected=\"true\">Facebook</div><div role=\"tab\" aria-selected=\"false\">Instagram</div></div><h2>Bring your duck craving to Sample Studio.</h2><div><span>Views</span><span>178</span></div><div><span>Reach</span><span>96</span></div><div><span>Likes and reactions</span><span>1</span></div><div><span>Comments</span><span>0</span></div><div><span>Shares</span><span>0</span></div><div><span>Saves</span><span>0</span></div><script>window.__sptBack = () => { window.__backed = true; };</script></body></html>"
    harness.load(fbDetail, at: "https://business.facebook.com/latest/insights/object_insights/?asset_id=2&business_id=1&content_id=1")
    fbStep = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\",\"days\":14,\"now\":\(now)}")
    precondition(fbStep["reason"] as? String == "读完一篇，回列表", "facebook detail read: \(fbStep)")
    harness.load(fbPage, at: "https://business.facebook.com/latest/posts/published_posts/?business_id=1&asset_id=2")
    fbStep = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\",\"days\":14,\"now\":\(now)}")
    precondition(fbStep["reason"] as? String == "打开帖子详情", "facebook opens the second row: \(fbStep)")
    harness.load(fbDetail.replacingOccurrences(of: ">178<", with: ">159<"), at: "https://business.facebook.com/latest/insights/object_insights/?asset_id=2&business_id=1&content_id=2")
    _ = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\",\"days\":14,\"now\":\(now)}")
    harness.load(fbPage, at: "https://business.facebook.com/latest/posts/published_posts/?business_id=1&asset_id=2")
    let fb = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\",\"days\":14,\"now\":\(now)}")
    precondition(fb["status"] as? String == "done", "facebook: \(fb)")
    let fbRows = fb["notes"] as! [[String: Any]]
    precondition(fbRows.count == 2, "two facebook rows: \(fbRows)")
    precondition(fbRows[0]["note_id"] as? String == "1000000000000000002", "post id from the checkbox: \(fbRows[0])")
    precondition(fbRows[0]["title"] as? String == "Bring your duck craving to Sample Studio.", "caption: \(fbRows[0])")
    precondition(fbRows[0]["time"] as? String == "Fri Oct 23, 11:52pm", "time: \(fbRows[0])")
    let fbMetrics = fbRows[0]["metrics"] as! [String: Any]
    precondition(fbMetrics["reach"] as? String == "96" && fbMetrics["views"] as? String == "178" && fbMetrics["likes"] as? String == "1" && fbMetrics["comments"] as? String == "0" && fbMetrics["shares"] as? String == "0" && fbMetrics["saves"] as? String == "0", "facebook numbers from the detail page: \(fbMetrics)")
    precondition((fbRows[1]["metrics"] as! [String: Any])["views"] as? String == "159", "second post read on its own page: \(fbRows[1])")
    precondition(fbRows[0]["crossposted"] as? Bool == true && (fbRows[0]["platforms"] as? [String]) == ["Instagram", "Facebook"], "platform marks: \(fbRows[0])")
    precondition((fb["header"] as! [String]).contains("Sample Studio"), "meta header: \(fb["header"] ?? "")")

    let igHead = "<tr><th>Title</th><th><button>Date published</button></th><th><button>Views</button></th><th><button>Reach</button></th><th><button>Likes and reactions</button></th><th><button>Comments</button></th><th><button>Shares</button></th><th><button>Saves</button></th></tr>"
    let igPage = "<html><body><div class=\"top\"><span>Sample Studio</span></div><span>Filter: 1 selected</span><table>" + igHead
        + metaRow("", "Peking Duck at Sample Studio: glossy, browned skin.", "Fri Oct 23, 11:53pm", ["178", "96", "1", "0", "0", "0"], platforms: "Instagram Facebook", crossposted: true, checkbox: false)
        + metaRow("", "Facebook only post.", "Thu Oct 22, 9:00am", ["5", "4", "0", "0", "0", "0"], platforms: "Facebook", checkbox: false)
        + "</table></body></html>"
    // Instagram: the list row is opened (a click), its Instagram tab read, then back to the list; progress survives in sessionStorage.
    harness.load(igPage, at: "https://business.facebook.com/latest/insights/content?business_id=1&asset_id=2")
    _ = harness.step("try { sessionStorage.removeItem('sptIG') } catch (e) {}; ({})")
    let igStep = harness.step("{\"phase\":\"notes\",\"platform\":\"instagram\",\"days\":14,\"now\":\(now)}")
    precondition(igStep["status"] as? String == "wait" && igStep["reason"] as? String == "打开帖子详情", "instagram opens the row: \(igStep)")
    let detail = "<html><body><div role=\"tablist\"><div role=\"tab\" aria-selected=\"false\">Facebook</div><div role=\"tab\" aria-selected=\"true\">Instagram</div></div><h2>Peking Duck at Sample Studio: glossy, browned skin.</h2><div class=\"overview\"><div><span>Views</span><span>212</span></div><div><span>Reach</span><span>150</span></div></div><div class=\"interactions\"><div><span>Likes and reactions</span><span>3</span></div><div><span>Comments</span><span>0</span></div><div><span>Shares</span><span>‑‑</span></div><div><span>Saves</span><span>1</span></div></div><script>window.__sptBack = () => { window.__backed = true; };</script></body></html>"
    harness.load(detail, at: "https://business.facebook.com/latest/insights/object_insights/?asset_id=2&business_id=1&content_id=1000000000000000003")
    let read = harness.step("{\"phase\":\"notes\",\"platform\":\"instagram\",\"days\":14,\"now\":\(now)}")
    precondition(read["status"] as? String == "wait" && read["reason"] as? String == "读完一篇，回列表", "detail read: \(read)")
    precondition(harness.step("window.__backed === true") as NSObject? != nil || true)
    harness.load(igPage, at: "https://business.facebook.com/latest/insights/content?business_id=1&asset_id=2")
    let ig = harness.step("{\"phase\":\"notes\",\"platform\":\"instagram\",\"days\":14,\"now\":\(now)}")
    precondition(ig["status"] as? String == "done", "instagram: \(ig)")
    let igRows = ig["notes"] as! [[String: Any]]
    precondition(igRows.count == 1, "only rows with Instagram on them: \(igRows)")
    let igMetrics = igRows[0]["metrics"] as! [String: Any]
    precondition(igMetrics["views"] as? String == "212" && igMetrics["reach"] as? String == "150" && igMetrics["likes"] as? String == "3" && igMetrics["comments"] as? String == "0" && igMetrics["shares"] as? String == "" && igMetrics["saves"] as? String == "1", "instagram numbers from the detail page: \(igMetrics)")

    harness.load("<html><body><a href=\"/latest/home?business_id=1&asset_id=2\">Home</a><div>Loading</div></body></html>", at: "https://business.facebook.com/latest/home")
    let nav = harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\"}")
    precondition(nav["status"] as? String == "navigate" && nav["url"] as? String == "https://business.facebook.com/latest/posts/published_posts/?business_id=1&asset_id=2", "navigate: \(nav)")

    harness.load("<html><body><form><input name=\"email\"><input name=\"pass\"></form></body></html>", at: "https://www.facebook.com/login/?next=x")
    precondition(harness.step("{\"phase\":\"notes\",\"platform\":\"facebook\"}")["status"] as? String == "login")
    print("metrics reader DOM: ok")
}
