import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct NativeDraftEditor: View {
    @ObservedObject var model: NativePublishingModel
    @Environment(\.presentationMode) private var presentation
    @State private var draft: NativeDraftForm
    @State private var selectedPlatform = "base"
    @State private var saving = false
    @State private var selecting = false
    @State private var message: String?
    @State private var hasSchedule = false
    @State private var schedule = Date()

    init(model: NativePublishingModel, initial: NativeDraftForm) {
        self.model = model
        _draft = State(initialValue: initial)
        if let date = ISO8601DateFormatter().date(from: initial.scheduledAt) {
            _hasSchedule = State(initialValue: true)
            _schedule = State(initialValue: date)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(draft.draftID == nil ? "新建内容" : "编辑内容")
                    .font(.system(size: 21, weight: .semibold))
                Spacer()
                Button("取消") { presentation.wrappedValue.dismiss() }
                    .keyboardShortcut(.cancelAction).disabled(saving || selecting)
                Button(saving ? "正在保存" : "保存草稿") { save() }
                    .keyboardShortcut("s", modifiers: .command)
                    .buttonStyle(.borderedProminent).tint(PublishingTheme.accent)
                    .disabled(!canSave || saving || selecting)
            }.padding(20)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    accountChoices
                    VStack(alignment: .leading, spacing: 9) {
                        Text("标题").font(.headline)
                        TextField("标题", text: $draft.title)
                            .textFieldStyle(.roundedBorder)
                    }
                    editor
                    mediaChoices
                    scheduling
                    if let message = message {
                        Text(message).foregroundColor(.orange).font(.callout)
                            .textSelection(.enabled)
                    }
                }.padding(20)
            }
        }
        .frame(width: 760, height: 680)
        .background(Color(red: 0.07, green: 0.06, blue: 0.09))
        .preferredColorScheme(.dark)
    }

    private var accountChoices: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("目标账号").font(.headline)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), alignment: .leading)]) {
                ForEach(model.accounts) { account in
                    Toggle(isOn: accountBinding(account.id)) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(account["name"].string ?? account["handle"].string ?? "账号")
                            Text(platformName(account["platform"].string ?? ""))
                                .font(.caption).foregroundColor(PublishingTheme.muted)
                        }
                    }.toggleStyle(.checkbox)
                }
            }
            if draft.accountIDs.isEmpty {
                HStack {
                    Text("平台草稿").font(.caption).foregroundColor(PublishingTheme.muted)
                    ForEach(model.platforms) { platform in
                        Toggle(platformName(platform.id), isOn: platformBinding(platform.id))
                            .toggleStyle(.checkbox).font(.caption)
                    }
                }.padding(.top, 4)
            }
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("正文").font(.headline)
                Picker("文案版本", selection: $selectedPlatform) {
                    Text("主稿").tag("base")
                    ForEach(targetPlatforms, id: \.self) { value in
                        Text(platformName(value)).tag(value)
                    }
                }.labelsHidden().frame(width: 190)
                Spacer()
                Text("\(editorText.wrappedValue.count) / 30,000")
                    .font(.caption).foregroundColor(PublishingTheme.muted)
            }
            TextEditor(text: editorText)
                .font(.system(size: 14)).frame(minHeight: 230)
                .padding(8).background(PublishingTheme.surface).cornerRadius(10)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12)))
            if selectedPlatform != "base" {
                Text("此平台正文留空时使用主稿").font(.caption)
                    .foregroundColor(PublishingTheme.muted)
            }
        }
    }

    private var mediaChoices: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("素材").font(.headline)
                Spacer()
                Button(selecting ? "正在添加" : "选择本机文件") { chooseFiles() }
                    .disabled(selecting || saving)
            }
            ForEach(Array(draft.mediaIDs.enumerated()), id: \.element) { index, identifier in
                HStack(spacing: 9) {
                    Text(String(format: "%02d", index + 1)).monospacedDigit()
                        .foregroundColor(PublishingTheme.accent)
                    Text(mediaName(identifier)).lineLimit(1)
                    Spacer()
                    Button { moveMedia(index, by: -1) } label: {
                        Image(systemName: "arrow.up")
                    }.disabled(index == 0).help("前移")
                    Button { moveMedia(index, by: 1) } label: {
                        Image(systemName: "arrow.down")
                    }.disabled(index == draft.mediaIDs.count - 1).help("后移")
                    Button { draft.mediaIDs.remove(at: index) } label: {
                        Image(systemName: "minus.circle")
                    }.help("移出本条内容")
                }.font(.caption).padding(9)
                    .background(PublishingTheme.surface).cornerRadius(8)
            }
            let unselected = model.media.filter { !draft.mediaIDs.contains($0.id) }
            if !unselected.isEmpty {
                DisclosureGroup("从素材库选择") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(unselected) { media in
                            Button {
                                draft.mediaIDs.append(media.id)
                            } label: {
                                Label(media["name"].string ?? "素材", systemImage: "plus.circle")
                            }.buttonStyle(.plain).font(.caption)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 9)
                }.font(.caption)
            }
            Text("仅引用原文件，尚未上传").font(.caption)
                .foregroundColor(PublishingTheme.muted)
        }
    }

    private var scheduling: some View {
        VStack(alignment: .leading, spacing: 9) {
            Toggle("记录计划时间", isOn: $hasSchedule).toggleStyle(.checkbox)
            if hasSchedule {
                DatePicker("计划时间", selection: $schedule)
                Text("保存本地排期，不会自动发布").font(.caption)
                    .foregroundColor(PublishingTheme.muted)
            }
        }
    }

    private var targetPlatforms: [String] {
        if !draft.accountIDs.isEmpty {
            return Array(Set(model.accounts.filter { draft.accountIDs.contains($0.id) }
                .compactMap { $0["platform"].string })).sorted()
        }
        return draft.platforms.sorted()
    }

    private var editorText: Binding<String> {
        Binding(get: {
            selectedPlatform == "base" ? draft.body : draft.variants[selectedPlatform] ?? ""
        }, set: { value in
            if selectedPlatform == "base" { draft.body = value }
            else { draft.variants[selectedPlatform] = value }
        })
    }

    private var canSave: Bool {
        !draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !draft.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !targetPlatforms.isEmpty && draft.title.count <= 300
            && draft.body.count <= 30000
    }

    private func accountBinding(_ identifier: String) -> Binding<Bool> {
        Binding(get: { draft.accountIDs.contains(identifier) }, set: { checked in
            if checked { draft.accountIDs.insert(identifier) }
            else { draft.accountIDs.remove(identifier) }
            selectedPlatform = "base"
        })
    }

    private func platformBinding(_ identifier: String) -> Binding<Bool> {
        Binding(get: { draft.platforms.contains(identifier) }, set: { checked in
            if checked { draft.platforms.insert(identifier) }
            else { draft.platforms.remove(identifier) }
            selectedPlatform = "base"
        })
    }

    private func platformName(_ identifier: String) -> String {
        ["xiaohongshu": "rednote", "instagram": "Instagram", "facebook": "Facebook",
         "tiktok": "TikTok", "youtube": "YouTube", "google_business": "Google 商家"][identifier] ?? identifier
    }

    private func mediaName(_ identifier: String) -> String {
        model.media.first { $0.id == identifier }?["name"].string ?? "未找到素材 · \(identifier.prefix(8))"
    }

    private func moveMedia(_ index: Int, by offset: Int) {
        let target = index + offset
        guard draft.mediaIDs.indices.contains(target) else { return }
        draft.mediaIDs.swapAt(index, target)
    }

    private func chooseFiles() {
        let panel = NSOpenPanel()
        panel.title = "选择本地素材"
        panel.prompt = "添加素材"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.movie, .image]
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        selecting = true
        message = nil
        let paths = panel.urls.map(\.path)
        Task {
            do {
                let identifiers = try await model.register(paths: paths)
                for identifier in identifiers where !draft.mediaIDs.contains(identifier) {
                    draft.mediaIDs.append(identifier)
                }
            } catch { message = error.localizedDescription }
            selecting = false
        }
    }

    private func save() {
        saving = true
        message = nil
        draft.platforms = Set(targetPlatforms)
        draft.scheduledAt = hasSchedule ? ISO8601DateFormatter().string(from: schedule) : ""
        Task {
            do {
                try await model.save(draft)
                presentation.wrappedValue.dismiss()
            } catch { message = error.localizedDescription }
            saving = false
        }
    }
}
