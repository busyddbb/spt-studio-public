import AppKit
import AVKit
import SwiftUI

func workspacePostMetrics(_ post: WorkspaceJSON, window: String) -> WorkspaceJSON {
    if window == "latest" { return post["metrics"] }
    if post["metrics_by_window"][window] != .null { return post["metrics_by_window"][window] }
    return post["metric_window"].string == window ? post["metrics"] : .null
}

func workspacePostSample(_ post: WorkspaceJSON, window: String) -> (String?, String?) {
    let cohort = window == "latest" ? post["metric_window"].string : window
    guard let cohort = cohort else { return (nil, nil) }
    if post["metric_observed_at_by_window"] != .null {
        return (cohort, post["metric_observed_at_by_window"][cohort].string)
    }
    return (cohort, cohort == post["metric_window"].string ? post["observed_at"].string : nil)
}

struct NativePostMetrics: View {
    let post: WorkspaceJSON
    let window: String
    private var keys: [(String, String)] {
        let format = post["format"].string ?? ""
        if format.contains("video") || format.contains("reel") || post["duration_sec"].number != nil {
            return [("views", "播放量"), ("completion_rate", "完播率"),
                    ("avg_watch_time_sec", "平均时长"), ("interactions", "互动")]
        }
        return [("views", "浏览量"), ("likes", "赞"), ("saves", "收藏"), ("comments", "评论")]
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], alignment: .leading, spacing: 16) {
                ForEach(keys, id: \.0) { key, label in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(label).font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                        Text(metricText(key)).font(.system(size: 25, weight: .semibold)).monospacedDigit()
                    }
                }
            }
            sampleLabel.font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
        }
    }
    private func metricText(_ key: String) -> String {
        let value = workspacePostMetrics(post, window: window)[key].number
        guard value != nil else { return "—" }
        let suffix = key == "completion_rate" ? "%" : key == "avg_watch_time_sec" ? "s" : ""
        return workspaceAmount(value) + suffix
    }
    private var sampleLabel: Text {
        let metrics = workspacePostMetrics(post, window: window)
        let hasValues = keys.contains { metrics[$0.0].number != nil }
        guard hasValues else { return Text("此节点尚未收录指标") }
        let (cohort, at) = workspacePostSample(post, window: window)
        return Text("\(cohort ?? "历史") · \(at == nil ? "采样日期未知" : workspaceDate(at) + " 采样")")
    }
}

struct NativePostDetail: View {
    @ObservedObject var store: NativeWorkspaceStore
    let post: WorkspaceRecord
    let account: WorkspaceRecord?
    let window: String
    let onOpenWork: (WorkspaceRecord) -> Void
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text(workspacePostTitle(post.raw)).font(.system(size: 21, weight: .semibold))
                    Text("\(account?["brand"].string ?? "") · \(account?["platform_label"].string ?? "")")
                        .font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
                }
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark") }
                    .buttonStyle(.plain).accessibilityLabel("关闭内容记录")
            }.padding(22)
            Divider().overlay(WorkspacePalette.line)
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if let path = post["preview_url"].string, let url = store.localURL(path) {
                        NativeWorkspaceMedia(url: url, video: true).frame(height: 285)
                    } else if let path = post["cover"].string {
                        NativeWorkspaceImage(url: store.localURL(path), fit: true).frame(height: 285)
                    }
                    NativePostMetrics(post: post.raw, window: window)
                    HStack {
                        Text(post["caption_complete"].bool == true ? "完整文案" : "记录文案")
                            .font(.system(size: 15, weight: .semibold))
                        Spacer()
                        if let caption = post["caption"].string {
                            Button("复制文案") { workspaceCopy(caption) }
                        }
                    }
                    Text(post["caption"].string ?? "未收录文案")
                        .font(.system(size: 14)).lineSpacing(6).textSelection(.enabled)
                    HStack {
                        if let id = post["work_id"].string,
                           let work = store.works.first(where: { $0.id == id }) {
                            Button("对应作品") {
                                dismiss()
                                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { onOpenWork(work) }
                            }
                        }
                        if let url = workspaceExternalURL(post["url"].string) {
                            Button("平台原文") { NSWorkspace.shared.open(url) }
                        }
                    }
                    DisclosureGroup("来源与采样") {
                        VStack(alignment: .leading, spacing: 8) {
                            if let identifier = post["content_id"].string { Text("内容编号：\(identifier)") }
                            let sample = workspacePostSample(post.raw, window: window)
                            if let cohort = sample.0 { Text("节点：\(cohort)") }
                            if let at = sample.1 { Text("采样：\(at)") }
                            Text(post["source"].string ?? "来源未记载").textSelection(.enabled)
                            ForEach(Array(post["issues"].array.enumerated()), id: \.offset) { _, item in
                                Text(item.string ?? "").foregroundColor(.orange)
                            }
                        }.font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 10)
                    }
                }.padding(22)
            }
        }.frame(width: 720, height: 650)
            .background(WorkspacePalette.panel).foregroundColor(Color(white: 0.96))
            .preferredColorScheme(.dark)
    }
}

func workspaceCopy(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}

struct NativeWorkspaceMedia: View {
    let url: URL
    let video: Bool
    @State private var player: AVPlayer?
    var body: some View {
        Group {
            if video {
                VideoPlayer(player: player)
                    .onAppear { player = AVPlayer(url: url) }
                    .onChange(of: url) { next in player?.pause(); player = AVPlayer(url: next) }
                    .onDisappear { player?.pause(); player = nil }
            } else { NativeWorkspaceImage(url: url, fit: true) }
        }
        .background(Color.black.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

struct NativeWorkDetail: View {
    @ObservedObject var store: NativeWorkspaceStore
    let work: WorkspaceRecord
    @Environment(\.dismiss) private var dismiss
    @State private var detail: WorkspaceJSON = .null
    @State private var loading = true
    @State private var error: String?
    @State private var tab = "versions"
    @State private var version = ""
    @State private var preview = ""
    private var versions: [WorkspaceJSON] { detail["versions"].array }
    private var selectedVersion: WorkspaceJSON {
        versions.first { $0["name"].string == version } ?? .null
    }
    private var candidates: [WorkspaceJSON] {
        detail["finals"].array + versions.flatMap {
            $0["media"].array + $0["returns"].array + $0["references"].array
        }
    }
    private var selectedMedia: WorkspaceJSON? {
        candidates.first { $0["url"].string == preview }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(WorkspacePalette.line)
            if loading { ProgressView("正在读取作品").frame(maxWidth: .infinity, maxHeight: .infinity) }
            else if let error = error { Text(error).foregroundColor(.orange).padding(30).frame(maxWidth: .infinity, maxHeight: .infinity) }
            else {
                HStack(alignment: .top, spacing: 0) {
                    previewPane.frame(width: 330)
                    Divider().overlay(WorkspacePalette.line)
                    VStack(alignment: .leading, spacing: 0) {
                        Picker("作品资料", selection: $tab) {
                            Text("版本 \(versions.count)").tag("versions")
                            Text("文案 \(detail["package"].object.count)").tag("captions")
                            Text("记录 \(detail["records"].array.count)").tag("records")
                            Text("文件 \(detail["finals"].array.count)").tag("files")
                        }.pickerStyle(.segmented).labelsHidden().padding(18)
                        Divider().overlay(WorkspacePalette.line)
                        ScrollView { detailContent.padding(20).frame(maxWidth: .infinity, alignment: .topLeading) }
                    }
                }
            }
        }
        .frame(width: 960, height: 680)
        .background(WorkspacePalette.panel).foregroundColor(Color(white: 0.96))
        .preferredColorScheme(.dark)
        .task { await load() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                Text(work["title"].string ?? "作品").font(.system(size: 21, weight: .semibold))
                Text("\(work["client"].string ?? "") · \(work["date"].string ?? "") · \(workspaceStatus(work["status"].string))")
                    .font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
            }
            Spacer()
            Button { dismiss() } label: { Image(systemName: "xmark") }
                .buttonStyle(.plain).accessibilityLabel("关闭作品详情")
        }.padding(22)
    }

    private var previewPane: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let media = selectedMedia, let path = media["url"].string, let url = store.localURL(path) {
                    NativeWorkspaceMedia(url: url, video: isVideo(media)).frame(height: 290)
                    Text(media["name"].string ?? "预览文件").font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                } else {
                    NativeWorkspaceImage(url: store.localURL(work["cover"].string ?? ""), fit: true).frame(height: 290)
                }
                Picker("预览", selection: $preview) {
                    Text("作品封面").tag("")
                    ForEach(Array(candidates.enumerated()), id: \.offset) { _, file in
                        Text((file["name"].string ?? "文件") + (work["media_match"].string == "mismatch" && file["role"].string == "final" ? " · 与当前记录不同" : ""))
                            .tag(file["url"].string ?? "")
                    }
                }.labelsHidden().accessibilityLabel("选择预览文件")
                if work["media_match"].string == "mismatch" {
                    Label("本地成片与当前发布记录不同，不可据此重发。", systemImage: "exclamationmark.circle")
                        .font(.system(size: 12)).foregroundColor(.orange)
                }
                if let current = work["current_version"].string {
                    Text("当前采用 \(current)").font(.system(size: 12)).foregroundColor(WorkspacePalette.purple)
                }
                if let latest = work["latest_version"].string, latest != work["current_version"].string {
                    Text("最新编辑 \(latest)").font(.system(size: 12)).foregroundColor(WorkspacePalette.secondary)
                }
                DisclosureGroup("状态与版本依据") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array((work["status_basis"].array + work["selection_basis"].array).enumerated()), id: \.offset) { _, item in
                            Text(item["text"].string ?? "").font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                        }
                    }.padding(.top, 8)
                }
            }.padding(20)
        }
    }

    @ViewBuilder private var detailContent: some View {
        switch tab {
        case "versions": versionContent
        case "captions": captionContent
        case "records": recordContent
        default: fileContent
        }
    }

    private var versionContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            if versions.isEmpty {
                Text("此作品没有版本目录或提示词。")
                    .font(.system(size: 13)).foregroundColor(WorkspacePalette.secondary)
            } else {
                HStack {
                    Picker("版本", selection: $version) {
                        ForEach(Array(versions.enumerated()), id: \.offset) { _, item in
                            Text((item["name"].string ?? "版本") + (item["is_current"].bool == true ? " · 当前采用" : ""))
                                .tag(item["name"].string ?? "")
                        }
                    }.labelsHidden().frame(maxWidth: 240)
                    Spacer()
                    if let prompt = selectedVersion["prompt"].string, !prompt.isEmpty {
                        Button("复制提示词") { workspaceCopy(prompt) }
                    }
                }
                Text("\(selectedVersion["is_current"].bool == true ? "当前采用版本" : "编辑稿") · \(selectedVersion["created_at"].string ?? "日期未知")")
                    .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                if let prompt = selectedVersion["prompt"].string, !prompt.isEmpty {
                    Text(prompt).font(.system(size: 13)).lineSpacing(5).textSelection(.enabled)
                }
                mediaGroup("编号素材", items: selectedVersion["media"].array)
                mediaGroup("生成结果", items: selectedVersion["returns"].array)
                mediaGroup("参考素材", items: selectedVersion["references"].array)
            }
        }
    }

    private func mediaGroup(_ title: String, items: [WorkspaceJSON]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if !items.isEmpty {
                Text("\(title) \(items.count)").font(.system(size: 14, weight: .semibold))
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    Button {
                        preview = item["url"].string ?? ""
                    } label: {
                        HStack {
                            Image(systemName: isVideo(item) ? "play.rectangle" : "photo")
                            Text(item["name"].string ?? "文件").lineLimit(2)
                            Spacer()
                            Image(systemName: "chevron.right").font(.system(size: 9))
                        }.font(.system(size: 12)).padding(.vertical, 6)
                    }.buttonStyle(.plain)
                }
            }
        }
    }

    private var captionContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            if detail["package"].object.isEmpty { empty("没有收录平台文案") }
            ForEach(detail["package"].object.keys.sorted(), id: \.self) { key in
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text(workspacePlatformName(key)).font(.system(size: 15, weight: .semibold))
                        Spacer()
                        Button("复制文案") { workspaceCopy(detail["package"][key].string ?? "") }
                    }
                    Text(detail["package"][key].string ?? "").font(.system(size: 13)).lineSpacing(5).textSelection(.enabled)
                }
            }
        }
    }

    private var recordContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if detail["records"].array.isEmpty { empty("没有发布记录") }
            ForEach(Array(detail["records"].array.enumerated()), id: \.offset) { _, record in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(workspacePlatformName(record["platform"].string ?? ""))
                            .font(.system(size: 14, weight: .semibold))
                        if record["state"].string != "current" {
                            Text("历史记录").font(.system(size: 11)).foregroundColor(.orange)
                        }
                        Spacer()
                        if let url = workspaceExternalURL(record["url"].string) {
                            Button("平台原文") { NSWorkspace.shared.open(url) }
                        }
                    }
                    Text(record["published_at"].string ?? "发布时间未记载")
                        .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                    Text(record["evidence"].string ?? "").font(.system(size: 12)).lineSpacing(4).textSelection(.enabled)
                    Divider().overlay(WorkspacePalette.line)
                }
            }
            Text("核验标记来自本地记录，未在此实时核验平台。")
                .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
            if !detail["timeline"].array.isEmpty {
                DisclosureGroup("制作时间记录") {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(detail["timeline"].array.enumerated()), id: \.offset) { _, item in
                            Text("\(item["at"].string ?? "") · \(item["description"].string ?? "")")
                                .font(.system(size: 11)).foregroundColor(WorkspacePalette.secondary)
                        }
                    }.padding(.top, 10)
                }
            }
        }
    }

    private var fileContent: some View {
        VStack(alignment: .leading, spacing: 20) {
            mediaGroup("成品文件", items: detail["finals"].array)
            if detail["finals"].array.isEmpty { empty("没有成品文件") }
            ForEach(Array(detail["source_documents"].array.enumerated()), id: \.offset) { _, document in
                DisclosureGroup(document["name"].string ?? "源文档") {
                    Text(document["text"].string ?? "").font(.system(size: 12)).lineSpacing(4)
                        .textSelection(.enabled).padding(.top, 10)
                }
            }
        }
    }

    private func empty(_ text: String) -> some View {
        Text(text).font(.system(size: 13)).foregroundColor(WorkspacePalette.secondary).padding(.vertical, 20)
    }

    private func isVideo(_ file: WorkspaceJSON) -> Bool {
        (file["mime_type"].string ?? "").hasPrefix("video/")
    }

    private func load() async {
        do {
            let value = try await store.detail(id: work.id)
            detail = value
            version = value["versions"].array.first { $0["is_current"].bool == true }?["name"].string
                ?? value["versions"].array.first { $0["name"].string == work["latest_version"].string }?["name"].string
                ?? value["versions"].array.first?["name"].string ?? ""
            if work["media_match"].string != "mismatch" {
                preview = value["finals"].array.first?["url"].string ?? ""
            }
        } catch { self.error = error.localizedDescription }
        loading = false
    }
}

func workspacePlatformName(_ key: String) -> String {
    switch key {
    case "instagram": return "Instagram"
    case "facebook": return "Facebook"
    case "tiktok": return "TikTok"
    case "rednote", "xiaohongshu": return "rednote"
    case "google_business", "google_business_profile": return "Google 商家资料"
    case "youtube": return "YouTube"
    default: return key
    }
}
