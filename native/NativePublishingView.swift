import AppKit
import SwiftUI

enum PublishingTheme {
    static let accent = Color(red: 0.73, green: 0.55, blue: 1)
    static let surface = Color(red: 0.13, green: 0.13, blue: 0.15)
    static let muted = Color(red: 0.71, green: 0.69, blue: 0.76)
}

struct NativeDraftForm: Identifiable {
    let id = UUID()
    var draftID: String?
    var title = ""
    var body = ""
    var accountIDs: Set<String> = []
    var platforms: Set<String> = ["xiaohongshu"]
    var mediaIDs: [String] = []
    var variants: [String: String] = [:]
    var scheduledAt = ""

    init(record: WorkspaceRecord? = nil) {
        guard let record = record else { return }
        draftID = record.id
        title = record["title"].string ?? ""
        body = record["body"].string ?? ""
        accountIDs = Set(record["account_ids"].array.compactMap(\.string))
        platforms = Set(record["platforms"].array.compactMap(\.string))
        mediaIDs = record["media_ids"].array.compactMap(\.string)
        variants = record["platform_variants"].object.compactMapValues(\.string)
        scheduledAt = record["scheduled_at"].string ?? ""
    }

    var payload: [String: Any] {
        ["title": title.trimmingCharacters(in: .whitespacesAndNewlines),
         "body": body.trimmingCharacters(in: .whitespacesAndNewlines),
         "account_ids": accountIDs.sorted(), "platforms": platforms.sorted(),
         "media_ids": mediaIDs, "platform_variants": variants,
         "scheduled_at": scheduledAt]
    }
}

enum NativePublishingAPI {
    static func request(_ path: String, method: String = "GET",
                        body: [String: Any]? = nil,
                        session: URLSession = .shared) async throws -> WorkspaceJSON {
        guard path.hasPrefix("/api/"), !path.contains(".."),
              let url = URL(string: "http://127.0.0.1:8766" + path) else {
            throw failure("本地接口地址无效")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 20
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let body = body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse,
              (200...299).contains(response.statusCode) else {
            let error = try? JSONDecoder().decode(WorkspaceJSON.self, from: data)
            throw failure(error?["error"].string ?? "本地服务暂时不可用")
        }
        return try JSONDecoder().decode(WorkspaceJSON.self, from: data)
    }

    static func failure(_ text: String) -> NSError {
        NSError(domain: "MediaDesk.NativePublishing", code: 1,
                userInfo: [NSLocalizedDescriptionKey: text])
    }
}

@MainActor final class NativePublishingModel: ObservableObject {
    @Published var accounts: [WorkspaceRecord] = []
    @Published var drafts: [WorkspaceRecord] = []
    @Published var media: [WorkspaceRecord] = []
    @Published var platforms: [WorkspaceRecord] = []
    @Published var error: String?
    @Published var loading = false

    func reload() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        do {
            async let state = NativePublishingAPI.request("/api/state?dataset=real")
            async let assets = NativePublishingAPI.request("/api/media")
            let (result, library) = try await (state, assets)
            accounts = result["accounts"].array.map { WorkspaceRecord(raw: $0) }
            drafts = result["drafts"].array.map { WorkspaceRecord(raw: $0) }
            platforms = result["platforms"].array.filter {
                $0["kind"].string == "social"
            }.map { WorkspaceRecord(raw: $0) }
            media = library["jobs"].array.map { WorkspaceRecord(raw: $0) }
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    func register(paths: [String]) async throws -> [String] {
        let result = try await NativePublishingAPI.request(
            "/api/media/register", method: "POST", body: ["paths": paths])
        let records = result["jobs"].array.map { WorkspaceRecord(raw: $0) }
        for record in records {
            if let index = media.firstIndex(where: { $0.id == record.id }) {
                media[index] = record
            } else { media.append(record) }
        }
        return records.map(\.id)
    }

    func save(_ draft: NativeDraftForm) async throws {
        let identifier = draft.draftID
        let path = identifier.map { "/api/drafts/" + $0 } ?? "/api/drafts"
        let result = try await NativePublishingAPI.request(
            path, method: identifier == nil ? "POST" : "PATCH", body: draft.payload)
        let record = WorkspaceRecord(raw: result["draft"])
        guard !record.id.isEmpty else { throw NativePublishingAPI.failure("草稿未能保存") }
        drafts.removeAll { $0.id == record.id }
        drafts.insert(record, at: 0)
    }

    func saveAccount(_ account: NativeAccountForm) async throws {
        let path = account.accountID.map { "/api/accounts/" + $0 } ?? "/api/accounts"
        let result = try await NativePublishingAPI.request(
            path, method: account.accountID == nil ? "POST" : "PATCH", body: account.payload)
        let record = WorkspaceRecord(raw: result["account"])
        guard !record.id.isEmpty else { throw NativePublishingAPI.failure("账号档案未能保存") }
        accounts.removeAll { $0.id == record.id }
        accounts.append(record)
    }
}

struct NativePublishingView: View {
    @ObservedObject var store: NativeWorkspaceStore
    let onOpenAccount: (String) -> Void
    let onOpenLegacy: (String) -> Void
    @StateObject private var model = NativePublishingModel()
    @State private var editing: NativeDraftForm?
    @State private var editingAccount: NativeAccountForm?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    Text("发布").font(.system(size: 28, weight: .bold))
                    Spacer()
                    Button { editing = NativeDraftForm() } label: {
                        Label("新建内容", systemImage: "square.and.pencil")
                    }.buttonStyle(.borderedProminent).tint(PublishingTheme.accent)
                }
                if let error = model.error {
                    HStack {
                        Text(error).foregroundColor(.orange)
                        Button("重试") { Task { await model.reload() } }
                    }
                }
                accountSection
                draftSection
            }.padding(24)
        }
        .task { await model.reload() }
        .onReceive(store.$loading) { loading in
            if !loading { Task { await model.reload() } }
        }
        .sheet(item: $editing) { draft in
            NativeDraftEditor(model: model, initial: draft)
        }
        .sheet(item: $editingAccount) { account in
            NativeAccountEditor(model: model, initial: account) {
                await model.reload()
                await store.reload()
            }
        }
    }

    private var accountSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("账号").font(.headline)
                Spacer()
                Button { editingAccount = NativeAccountForm() } label: {
                    Label("添加账号", systemImage: "plus")
                }.buttonStyle(.bordered)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 14)], spacing: 14) {
                ForEach(displayAccounts) { account in
                    accountCard(account)
                }
            }
        }
    }

    private func accountCard(_ account: WorkspaceRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "person.crop.square.fill")
                    .font(.system(size: 25)).foregroundColor(PublishingTheme.accent)
                VStack(alignment: .leading, spacing: 3) {
                    Text(accountTitle(account))
                        .font(.system(size: 14, weight: .semibold))
                    Text(account["platform_label"].string ?? "")
                        .font(.caption).foregroundColor(PublishingTheme.muted)
                }
            }
            Text(account["handle"].string ?? "尚未关联账号")
                .font(.caption).foregroundColor(PublishingTheme.muted).lineLimit(1)
            if let identifier = account["legacy_account_id"].string, !identifier.isEmpty {
                HStack {
                    Button("官方后台") { onOpenAccount(identifier) }.buttonStyle(.bordered)
                    Spacer()
                    Button("编辑档案") { editAccount(identifier) }
                        .buttonStyle(.plain).font(.caption)
                        .foregroundColor(PublishingTheme.muted)
                }
            } else if account["readonly"].bool == true {
                Text("只读资料").font(.caption).foregroundColor(PublishingTheme.muted)
            } else {
                Button("关联账号") {
                    editingAccount = NativeAccountForm(preset: account)
                }.buttonStyle(.bordered)
            }
        }.frame(maxWidth: .infinity, alignment: .leading).padding(18)
            .background(PublishingTheme.surface).cornerRadius(18)
    }

    private var displayAccounts: [WorkspaceRecord] {
        let knownIDs = Set(store.accounts.compactMap { $0["legacy_account_id"].string })
        let additional = model.accounts.filter { !knownIDs.contains($0.id) }.map { account in
            var value = account.raw.object
            value["id"] = .string("local:" + account.id)
            value["legacy_account_id"] = .string(account.id)
            value["platform_label"] = .string(NativeAccountForm.platformName(account["platform"].string ?? ""))
            return WorkspaceRecord(raw: .object(value))
        }
        return store.accounts + additional
    }

    private func accountTitle(_ account: WorkspaceRecord) -> String {
        if let identifier = account["legacy_account_id"].string,
           let current = model.accounts.first(where: { $0.id == identifier }) {
            return current["name"].string ?? account["brand"].string ?? "账号"
        }
        return account["brand"].string ?? account["name"].string ?? "账号"
    }

    private func editAccount(_ identifier: String) {
        if let record = model.accounts.first(where: { $0.id == identifier }) {
            editingAccount = NativeAccountForm(record: record)
        } else {
            Task {
                await model.reload()
                guard let record = model.accounts.first(where: { $0.id == identifier }) else {
                    model.error = "账号档案暂时未能读取，请重试"
                    return
                }
                editingAccount = NativeAccountForm(record: record)
            }
        }
    }

    private var draftSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("本地草稿").font(.headline)
                Text("\(model.drafts.count)").font(.caption).foregroundColor(PublishingTheme.muted)
                Spacer()
                Menu("更多工具") {
                    Button("原发布工具") { onOpenLegacy("publish") }
                }.menuStyle(.borderlessButton).fixedSize()
                    .foregroundColor(PublishingTheme.muted)
            }
            if model.drafts.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "square.and.pencil").font(.system(size: 25))
                    Text(model.loading ? "正在读取草稿" : "还没有本地草稿")
                        .font(.subheadline)
                }.foregroundColor(PublishingTheme.muted)
                    .frame(maxWidth: .infinity).padding(36)
                    .background(PublishingTheme.surface).cornerRadius(18)
            } else {
                ForEach(model.drafts) { draft in
                    draftRow(draft)
                }
            }
        }
    }

    private func draftRow(_ draft: WorkspaceRecord) -> some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(draft["title"].string ?? "未命名内容").fontWeight(.semibold)
                Text(draft["body"].string ?? "").font(.caption)
                    .foregroundColor(PublishingTheme.muted).lineLimit(2)
                Text(statusLabel(draft["status"].string))
                    .font(.caption2).foregroundColor(PublishingTheme.accent)
            }
            Spacer()
            Button("编辑") { editing = NativeDraftForm(record: draft) }
                .buttonStyle(.bordered)
        }.padding(18).background(PublishingTheme.surface).cornerRadius(14)
    }

    private func statusLabel(_ value: String?) -> String {
        ["draft": "草稿", "review": "待审核", "approved": "已批准"] [value ?? ""] ?? "本地记录"
    }
}
