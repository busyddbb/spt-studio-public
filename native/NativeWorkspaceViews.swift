import AppKit
import SwiftUI

// All workspace controls below are native SwiftUI views. WebKit is reserved for
// the account-specific official publishing pages owned by AppDelegate.
enum WorkspacePalette {
    static let background = Color(red: 0.055, green: 0.050, blue: 0.071)
    static let panel = Color(red: 0.125, green: 0.120, blue: 0.145)
    static let secondary = Color(red: 0.69, green: 0.67, blue: 0.74)
    static let purple = Color(red: 0.73, green: 0.55, blue: 0.98)
    static let line = Color.white.opacity(0.09)
}

struct WorkspacePanel<Content: View>: View {
    private let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        content.padding(20)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .background(WorkspacePalette.panel)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(WorkspacePalette.line))
    }
}

struct WorkspaceGlass: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .sidebar
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

enum WorkspaceRoute: String, CaseIterable, Identifiable {
    case operations, library, intelligence, publishing, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .operations: return "运营"
        case .library: return "专业库"
        case .intelligence: return "情报"
        case .publishing: return "发布"
        case .settings: return "设置"
        }
    }
    var symbol: String {
        switch self {
        case .operations: return "square.grid.2x2"
        case .library: return "folder"
        case .intelligence: return "doc.text"
        case .publishing: return "paperplane"
        case .settings: return "gearshape"
        }
    }
}

struct NativeWorkspaceRoot: View {
    @ObservedObject var store: NativeWorkspaceStore
    let onOpenAccount: (String) -> Void
    let onOpenLegacy: (String) -> Void
    @State private var route: WorkspaceRoute = .operations
    @State private var query = ""
    @State private var detailWork: WorkspaceRecord?

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            VStack(spacing: 0) {
                toolbar
                if let error = store.error {
                    HStack {
                        Image(systemName: "exclamationmark.circle")
                        Text(error).lineLimit(2)
                        Spacer()
                        Button("重试") { Task { await store.reload() } }
                    }
                    .font(.system(size: 12)).foregroundColor(.orange)
                    .padding(.horizontal, 24).padding(.vertical, 10)
                }
                content.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(WorkspacePalette.background)
        .foregroundColor(Color(white: 0.96))
        .preferredColorScheme(.dark)
        .frame(minWidth: 820, minHeight: 560)
        .sheet(item: $detailWork) { work in
            NativeWorkDetail(store: store, work: work)
        }
        .task { if store.accounts.isEmpty { await store.reload() } }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Text("M").font(.system(size: 21, weight: .heavy))
                    .foregroundColor(WorkspacePalette.background)
                    .frame(width: 32, height: 32).background(Color(white: 0.95))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                Text("SPT").font(.system(size: 18, weight: .semibold))
            }.padding(.horizontal, 12).padding(.top, 24).padding(.bottom, 24)
            ForEach(WorkspaceRoute.allCases.filter { $0 != .settings }) { item in
                navigationButton(item)
            }
            Spacer(minLength: 24)
            navigationButton(.settings)
            Text("本地工作区").font(.system(size: 11))
                .foregroundColor(WorkspacePalette.secondary)
                .padding(.horizontal, 14).padding(.top, 20).padding(.bottom, 18)
        }
        .padding(.horizontal, 12)
        .frame(width: 176)
        .background(WorkspaceGlass().overlay(WorkspacePalette.purple.opacity(0.065)))
        .overlay(Rectangle().fill(WorkspacePalette.line).frame(width: 1), alignment: .trailing)
    }

    private func navigationButton(_ item: WorkspaceRoute) -> some View {
        Button { route = item } label: {
            HStack(spacing: 12) {
                Image(systemName: item.symbol).font(.system(size: 17)).frame(width: 20)
                Text(item.title).font(.system(size: 14, weight: route == item ? .semibold : .regular))
                Spacer()
            }
            .padding(.horizontal, 14).padding(.vertical, 13)
            .foregroundColor(route == item ? Color(white: 0.98) : WorkspacePalette.secondary)
            .background(route == item ? WorkspacePalette.purple.opacity(0.23) : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(route == item ? WorkspacePalette.purple.opacity(0.25) : .clear))
        }.buttonStyle(.plain).accessibilityLabel(item.title)
    }

    private var toolbar: some View {
        HStack {
            Button { route = .library } label: {
                Label("搜索作品", systemImage: "magnifyingglass")
                    .foregroundColor(WorkspacePalette.secondary)
            }.buttonStyle(.plain).keyboardShortcut("k", modifiers: .command)
            Spacer()
            if store.loading { ProgressView().scaleEffect(0.65).frame(width: 20) }
            Button { Task { await store.reload() } } label: {
                Label("重读本地资料", systemImage: "arrow.clockwise")
                    .font(.system(size: 12)).padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Color.white.opacity(0.045)).clipShape(Capsule())
                    .overlay(Capsule().stroke(WorkspacePalette.line))
            }.buttonStyle(.plain).disabled(store.loading)
        }
        .padding(.horizontal, 24).frame(height: 58)
        .background(WorkspaceGlass().overlay(WorkspacePalette.background.opacity(0.55)))
        .overlay(Rectangle().fill(WorkspacePalette.line).frame(height: 1), alignment: .bottom)
    }

    @ViewBuilder private var content: some View {
        switch route {
        case .operations:
            NativeOperationsView(store: store, onOpenAccount: onOpenAccount,
                                 onOpenLegacy: openTool, onOpenWork: { detailWork = $0 })
        case .library:
            NativeLibraryView(store: store, query: $query, onOpenWork: { detailWork = $0 })
        case .intelligence: NativeIntelligenceView(store: store)
        case .publishing:
            NativePublishingView(store: store, onOpenAccount: onOpenAccount, onOpenLegacy: openTool)
        case .settings: settings
        }
    }

    private var settings: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                workspaceHeading("设置")
                WorkspacePanel {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("工作区").font(.system(size: 18, weight: .semibold))
                        Text(store.health["workspace_path"].string ?? "未连接")
                            .font(.system(size: 13)).textSelection(.enabled)
                        Text("\(store.works.count) 件作品 · 原文件保留原位")
                            .font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
                    }
                }
                WorkspacePanel {
                    VStack(alignment: .leading, spacing: 14) {
                        Text("账号与资料").font(.system(size: 18, weight: .semibold))
                        Text("\(store.accounts.count) 个平台入口")
                        Text("运营数字来自本地历史记录；官方最新数据在账号后台查看。")
                            .font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
                        Button("管理账号档案") { openTool("accounts") }
                    }
                }
            }.padding(24)
        }
    }

    private func openTool(_ destination: String) {
        if destination == "accounts" { route = .publishing }
        else { onOpenLegacy(destination) }
    }
}

func workspaceHeading(_ title: String, subtitle: String? = nil) -> some View {
    VStack(alignment: .leading, spacing: 6) {
        Text(title).font(.system(size: 28, weight: .bold))
        if let subtitle = subtitle {
            Text(subtitle).font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
        }
    }
}

func workspaceAmount(_ value: Double?) -> String {
    guard let value = value, value.isFinite else { return "—" }
    let formatter = NumberFormatter()
    formatter.numberStyle = .decimal
    formatter.maximumFractionDigits = 1
    return formatter.string(from: NSNumber(value: value)) ?? "—"
}

func workspaceDate(_ value: String?) -> String {
    guard let value = value, !value.isEmpty else { return "日期未知" }
    guard value.count >= 10 else { return value }
    let part = String(value.prefix(10))
    return String(part.dropFirst(5)).replacingOccurrences(of: "-", with: "/")
}

func workspacePostTitle(_ value: WorkspaceJSON) -> String {
    let raw = value["title"].string ?? value["content_id"].string ?? "内容记录"
    if raw == "unknown_official_menu_identity" { return "菜品待核对" }
    let hasChinese = raw.unicodeScalars.contains { (0x4e00...0x9fff).contains($0.value) }
    if raw.contains("_") && !hasChinese {
        return "内容记录"
    }
    if raw.count > 11, raw.prefix(10).contains("-"), raw.dropFirst(10).first == "_" {
        return String(raw.dropFirst(11)).replacingOccurrences(of: "_", with: " · ")
    }
    return raw
}

struct WorkspacePlatformMark: View {
    let platform: String
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 8).fill(tint)
            Group {
                switch platform {
                case "rednote", "xiaohongshu": Text("小红书").font(.system(size: 7, weight: .bold))
                case "instagram": Image(systemName: "camera").font(.system(size: 17, weight: .semibold))
                case "facebook": Text("f").font(.system(size: 22, weight: .bold))
                case "tiktok": Image(systemName: "music.note").font(.system(size: 17, weight: .bold))
                case "google_business_profile", "google_business": Text("G").font(.system(size: 17, weight: .bold))
                case "yelp": Image(systemName: "asterisk").font(.system(size: 18, weight: .bold))
                default: Image(systemName: "person.crop.circle")
                }
            }.foregroundColor(.white)
        }.frame(width: 29, height: 29)
    }
    private var tint: Color {
        switch platform {
        case "rednote", "xiaohongshu", "yelp": return Color(red: 0.88, green: 0.14, blue: 0.28)
        case "instagram": return Color(red: 0.72, green: 0.24, blue: 0.56)
        case "facebook": return Color(red: 0.18, green: 0.39, blue: 0.85)
        case "google_business_profile", "google_business": return Color(red: 0.26, green: 0.48, blue: 0.82)
        default: return Color(white: 0.19)
        }
    }
}

private struct NativeOperationsView: View {
    @ObservedObject var store: NativeWorkspaceStore
    let onOpenAccount: (String) -> Void
    let onOpenLegacy: (String) -> Void
    let onOpenWork: (WorkspaceRecord) -> Void
    @State private var accountID = ""
    @State private var postID = ""
    @State private var metric = "followers"
    @State private var window = "latest"
    @State private var expandedPost: WorkspaceRecord?
    private var selectedAccount: WorkspaceRecord? {
        store.accounts.first { $0.id == accountID }
        ?? store.accounts.first { $0["platform"].string == "instagram" }
        ?? store.accounts.first
    }
    private var posts: [WorkspaceRecord] {
        store.posts.filter { $0["account_id"].string == selectedAccount?.id
            && $0["current"].bool != false
            && !["withdrawn", "deleted", "archived"].contains($0["status"].string ?? "") }
    }
    private var selectedPost: WorkspaceRecord? {
        posts.first { $0.id == postID }
        ?? posts.first { $0["cover"].string != nil && $0["caption_complete"].bool == true }
        ?? posts.first
    }

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    HStack {
                        workspaceHeading("运营总览")
                        Spacer()
                        Picker("数据节点", selection: $window) {
                            Text("最近留存").tag("latest")
                            Text("D1 · 24小时").tag("D1")
                            Text("D3 · 72小时").tag("D3")
                            Text("D7 · 7天").tag("D7")
                        }.labelsHidden().frame(width: 135)
                    }
                    if geometry.size.width > 960 {
                        HStack(alignment: .top, spacing: 16) {
                            accountsPanel.frame(width: 276)
                            postPanel.frame(maxWidth: .infinity)
                            intelligenceRail.frame(width: 246)
                        }
                    } else if geometry.size.width > 640 {
                        HStack(alignment: .top, spacing: 16) {
                            accountsPanel.frame(width: 260)
                            postPanel.frame(maxWidth: .infinity)
                        }
                        intelligenceRail
                    } else {
                        accountsPanel
                        postPanel
                        intelligenceRail
                    }
                    recentWorks
                }.padding(24)
            }
        }
        .sheet(item: $expandedPost) { post in
            NativePostDetail(store: store, post: post, account: selectedAccount,
                             window: window, onOpenWork: onOpenWork)
        }
    }

    private var accountsPanel: some View {
        WorkspacePanel {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("账号表现").font(.system(size: 19, weight: .semibold))
                    Spacer()
                    Picker("账号指标", selection: $metric) {
                        Text("粉丝").tag("followers")
                        Text("浏览").tag("views")
                        Text("互动").tag("interactions")
                    }.labelsHidden().frame(width: 80)
                }
                ForEach(store.accounts) { account in accountRow(account) }
                Divider().overlay(WorkspacePalette.line)
                HStack {
                    Text("本地快照 · \(workspaceDate(selectedAccount?["as_of"].string))")
                        .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                    Spacer()
                }
                if let id = selectedAccount?["legacy_account_id"].string {
                    Button { onOpenAccount(id) } label: {
                        Label("官方后台", systemImage: "arrow.up.right.square")
                            .frame(maxWidth: .infinity).padding(.vertical, 9)
                    }.buttonStyle(.plain)
                        .background(Color.white.opacity(0.05)).clipShape(Capsule())
                        .overlay(Capsule().stroke(WorkspacePalette.line))
                        .accessibilityLabel("打开\(selectedAccount?["brand"].string ?? "账号")官方后台")
                } else if selectedAccount?["readonly"].bool != true {
                    Button("关联账号") { onOpenLegacy("accounts") }
                }
            }
        }
    }

    private func accountRow(_ account: WorkspaceRecord) -> some View {
        let value = account["metrics"][metric].number
        let maximum = max(1, store.accounts.compactMap { $0["metrics"][metric].number }.max() ?? 1)
        let selected = selectedAccount?.id == account.id
        return Button {
            accountID = account.id
            postID = ""
        } label: {
            HStack(alignment: .center, spacing: 9) {
                WorkspacePlatformMark(platform: account["platform"].string ?? "")
                VStack(alignment: .leading, spacing: 3) {
                    Text(account["brand"].string ?? "账号").font(.system(size: 12, weight: .semibold))
                    Text(account["platform_label"].string ?? "")
                        .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                    GeometryReader { geometry in
                        Capsule().fill(Color.white.opacity(0.07))
                            .overlay(Capsule().fill(WorkspacePalette.purple)
                                .frame(width: value == nil ? 0 : max(2, geometry.size.width * CGFloat((value ?? 0) / maximum))), alignment: .leading)
                    }.frame(height: 5).padding(.top, 3)
                }
                VStack(alignment: .trailing, spacing: 3) {
                    Text(value == nil ? account["display_metrics"][metric].string.map { "约 \($0)" } ?? "—" : workspaceAmount(value))
                        .font(.system(size: 12, weight: .medium)).monospacedDigit()
                    Text(account["as_of"].string == nil ? "未采集" : workspaceDate(account["as_of"].string))
                        .font(.system(size: 10)).foregroundColor(WorkspacePalette.secondary)
                }
            }
            .padding(.horizontal, 8).padding(.vertical, 10)
            .background(selected ? WorkspacePalette.purple.opacity(0.18) : .clear)
            .clipShape(RoundedRectangle(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).stroke(selected ? WorkspacePalette.purple.opacity(0.25) : .clear))
        }.buttonStyle(.plain)
            .accessibilityLabel("查看\(account["brand"].string ?? "") \(account["platform_label"].string ?? "")内容")
    }

    private var postPanel: some View {
        WorkspacePanel {
            if let post = selectedPost {
                VStack(alignment: .leading, spacing: 17) {
                    HStack(spacing: 10) {
                        WorkspacePlatformMark(platform: selectedAccount?["platform"].string ?? "")
                        VStack(alignment: .leading, spacing: 4) {
                            Text(workspacePostTitle(post.raw)).font(.system(size: 16, weight: .semibold))
                            Text(post["source_kind"].string == "metric_node" ? "历史记录" : "\(selectedAccount?["platform_label"].string ?? "") · \(workspaceDate(post["published_at"].string))")
                                .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                        }
                    }
                    if let cover = post["cover"].string, let url = store.localURL(cover) {
                        HStack(alignment: .top, spacing: 16) {
                            NativeWorkspaceImage(url: url, fit: true).frame(width: 145, height: 232)
                            VStack(alignment: .leading, spacing: 16) {
                                Text(post["caption"].string ?? "未收录文案")
                                    .font(.system(size: 12)).lineSpacing(4).lineLimit(5)
                                NativePostMetrics(post: post.raw, window: window)
                            }
                        }
                    } else {
                        NativePostMetrics(post: post.raw, window: window)
                        if post["caption"].string != nil {
                            Text(post["caption"].string ?? "").font(.system(size: 12)).lineLimit(5).lineSpacing(4)
                        } else { Text("未收录文案").font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary) }
                    }
                    HStack(spacing: 8) {
                        Button(post["caption_complete"].bool == true ? "查看全文" : "查看记录") { expandedPost = post }
                        if let workID = post["work_id"].string,
                           let work = store.works.first(where: { $0.id == workID }) {
                            Button("对应作品") { onOpenWork(work) }
                        }
                        if let url = workspaceExternalURL(post["url"].string) {
                            Button("平台原文") { NSWorkspace.shared.open(url) }
                        }
                    }.font(.system(size: 11))
                    if post["media_match"].string == "mismatch" {
                        Label("本地成品与当前发布版本不同", systemImage: "exclamationmark.circle")
                            .font(.system(size: 11)).foregroundColor(.orange)
                    }
                    Divider().overlay(WorkspacePalette.line)
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(posts.filter { $0.id != post.id }) { item in
                                Button { postID = item.id } label: {
                                    HStack {
                                        Text(workspacePostTitle(item.raw)).lineLimit(1)
                                        Spacer()
                                        Text(workspaceDate(item["published_at"].string)).foregroundColor(WorkspacePalette.secondary)
                                        Image(systemName: "chevron.right").font(.system(size: 9))
                                    }.font(.system(size: 12)).padding(.vertical, 9)
                                }.buttonStyle(.plain)
                            }
                        }
                    }.frame(maxHeight: 148)
                    Text("\(posts.count) 条\(post["source_kind"].string == "metric_node" ? "历史" : "内容")记录")
                        .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                }
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Text("账号内容").font(.system(size: 19, weight: .semibold))
                    Text("尚未收录内容记录").foregroundColor(WorkspacePalette.secondary)
                }.frame(minHeight: 170, alignment: .top)
            }
        }
    }

    private var recentWorks: some View {
        WorkspacePanel {
            VStack(alignment: .leading, spacing: 18) {
                Text("专业作品库").font(.system(size: 18, weight: .semibold))
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 170), spacing: 18)], spacing: 18) {
                    ForEach(store.works) { work in
                        NativeWorkCard(store: store, work: work, compact: true) { onOpenWork(work) }
                    }
                }
            }
        }
    }

    private var intelligenceRail: some View {
        VStack(alignment: .leading, spacing: 16) {
            WorkspacePanel {
                VStack(alignment: .leading, spacing: 18) {
                    Text("情报").font(.system(size: 19, weight: .semibold))
                    ForEach(Array(store.intelligence["news"].array.prefix(3).enumerated()), id: \.offset) { _, item in
                        NativeIntelligenceItem(item: item, compact: true)
                    }
                    Text("保存资料 · 非实时订阅").font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                }
            }
            WorkspacePanel {
                VStack(alignment: .leading, spacing: 12) {
                    Text("市场线索").font(.system(size: 18, weight: .semibold))
                    Text("\(Int(store.intelligence["candidate_active_count"].number ?? 0)) 条有效候选")
                        .font(.system(size: 15, weight: .semibold))
                    Text("\(Int(store.intelligence["candidate_count"].number ?? 0)) 条历史记录")
                        .font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
                }
            }
        }
    }
}

func workspaceExternalURL(_ string: String?) -> URL? {
    guard let string = string, let url = URL(string: string),
          ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
          url.user == nil, url.password == nil, url.host != nil else { return nil }
    return url
}

struct NativeWorkspaceImage: View {
    let url: URL?
    var fit = false
    var body: some View {
        ZStack {
            Color(white: 0.075)
            if let url = url {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        if fit { image.resizable().scaledToFit() }
                        else { image.resizable().scaledToFill() }
                    } else if phase.error != nil {
                        Image(systemName: "photo").foregroundColor(WorkspacePalette.secondary)
                    } else { ProgressView().scaleEffect(0.65) }
                }
            } else {
                VStack(spacing: 9) {
                    Image(systemName: "film").font(.system(size: 24))
                    Text("暂无封面").font(.system(size: 11))
                }.foregroundColor(WorkspacePalette.secondary)
            }
        }.clipped().clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

private struct NativeLibraryView: View {
    @ObservedObject var store: NativeWorkspaceStore
    @Binding var query: String
    let onOpenWork: (WorkspaceRecord) -> Void
    @State private var status = ""
    private var works: [WorkspaceRecord] {
        store.works.filter {
            (status.isEmpty || $0["status"].string == status)
            && (query.isEmpty || [$0["title"].string, $0["client"].string, $0["category"].string]
                .compactMap { $0 }.joined(separator: " ").localizedCaseInsensitiveContains(query))
        }
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    workspaceHeading("专业作品库", subtitle: "\(store.works.count) 件作品")
                    Spacer()
                    Button("刷新索引") { Task { await store.reindex() } }.disabled(store.loading)
                }
                HStack(spacing: 14) {
                    TextField("搜索作品、客户", text: $query).textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 420).accessibilityLabel("搜索作品、客户")
                    Spacer()
                    Picker("作品状态", selection: $status) {
                        Text("全部状态").tag("")
                        Text("已发布").tag("published")
                        Text("待发布").tag("ready")
                        Text("已成片").tag("cut")
                        Text("制作中").tag("wip")
                    }.labelsHidden().frame(width: 120)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), spacing: 22)], spacing: 26) {
                    ForEach(works) { work in
                        NativeWorkCard(store: store, work: work, compact: false) { onOpenWork(work) }
                    }
                }
                if works.isEmpty { Text("没有匹配的作品").foregroundColor(WorkspacePalette.secondary).padding(.vertical, 40) }
            }.padding(24)
        }
    }
}

struct NativeWorkCard: View {
    @ObservedObject var store: NativeWorkspaceStore
    let work: WorkspaceRecord
    let compact: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 9) {
                NativeWorkspaceImage(url: store.localURL(work["cover"].string ?? ""), fit: true)
                    .frame(height: compact ? 124 : 250)
                Text(work["title"].string ?? "作品").font(.system(size: compact ? 13 : 15, weight: .semibold)).lineLimit(1)
                Text("\(work["client"].string ?? "")  \(work["date"].string ?? "")")
                    .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                HStack {
                    Text(workspaceStatus(work["status"].string)).font(.system(size: 11))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(work["status"].string == "published" ? WorkspacePalette.purple.opacity(0.24) : Color.white.opacity(0.07))
                        .clipShape(Capsule())
                    Spacer()
                    Text(work["current_version"].string.map { "采用 \($0)" }
                         ?? work["latest_version"].string.map { "最新编辑 \($0)" } ?? "")
                        .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                }
                if work["media_match"].string == "mismatch" {
                    Text("本地成片与发布记录不同").font(.system(size: 11)).foregroundColor(.orange)
                }
            }.contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityLabel("查看\(work["title"].string ?? "作品")")
    }
}

func workspaceStatus(_ status: String?) -> String {
    switch status {
    case "published": return "已发布"
    case "ready": return "待发布"
    case "cut": return "已成片"
    default: return "制作中"
    }
}

private struct NativeIntelligenceView: View {
    @ObservedObject var store: NativeWorkspaceStore
    @State private var section = "news"
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                workspaceHeading("情报", subtitle: "保存的来源与研究 · 非实时订阅")
                Picker("情报分类", selection: $section) {
                    Text("官方动态").tag("news")
                    Text("研究资料").tag("research")
                    Text("市场线索").tag("candidates")
                }.pickerStyle(.segmented).frame(maxWidth: 420)
                ForEach(Array(store.intelligence[section].array.enumerated()), id: \.offset) { _, item in
                    WorkspacePanel { NativeIntelligenceItem(item: item, compact: false) }
                }
            }.padding(24)
        }
    }
}

private struct NativeIntelligenceItem: View {
    let item: WorkspaceJSON
    let compact: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                if let url = workspaceExternalURL(item["url"].string) { NSWorkspace.shared.open(url) }
            } label: {
                HStack(alignment: .top) {
                    Text(item["title"].string ?? "资料").multilineTextAlignment(.leading)
                        .font(.system(size: compact ? 12 : 16, weight: .semibold))
                    Spacer(minLength: 6)
                    Image(systemName: "arrow.up.right").font(.system(size: 10))
                        .foregroundColor(WorkspacePalette.secondary)
                }
            }.buttonStyle(.plain)
            Text("\(item["source"].string ?? item["platform"].string ?? "来源资料") · \(workspaceDate(item["published_at"].string ?? item["captured_at"].string))")
                .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
            if !compact {
                Text(item["summary"].string ?? item["notes"].string ?? "")
                    .font(.system(size: 13)).foregroundColor(WorkspacePalette.secondary).lineSpacing(4)
                if item["status"].string == "expired" { Text("已过期 · 历史线索").font(.system(size: 11)).foregroundColor(.orange) }
            }
        }.padding(.bottom, compact ? 5 : 0)
    }
}
