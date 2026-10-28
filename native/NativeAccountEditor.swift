import SwiftUI

struct NativeAccountForm: Identifiable {
    let id = UUID()
    var accountID: String?
    var name = ""
    var platform = "xiaohongshu"
    var handle = ""
    var brand = ""
    var notes = ""
    private var originalBrand = ""
    private var originalNotes = ""

    init(record: WorkspaceRecord? = nil, preset: WorkspaceRecord? = nil) {
        if let record = record {
            accountID = record.id
            name = record["name"].string ?? ""
            platform = record["platform"].string ?? "xiaohongshu"
            handle = record["handle"].string ?? ""
            brand = record["brand"].string ?? ""
            notes = record["notes"].string ?? ""
        } else if let preset = preset {
            name = preset["name"].string ?? preset["brand"].string ?? ""
            platform = Self.normalizedPlatform(preset["platform"].string ?? "xiaohongshu")
            handle = preset["handle"].string ?? preset["profile_url"].string ?? ""
            brand = preset["brand"].string ?? ""
        }
        originalBrand = brand
        originalNotes = notes
    }

    var payload: [String: Any] {
        var values: [String: Any] = [
            "name": name.trimmingCharacters(in: .whitespacesAndNewlines)
        ]
        if accountID == nil {
            values["platform"] = Self.normalizedPlatform(platform)
            values["handle"] = handle.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if accountID == nil || brand != originalBrand { values["brand"] = brand }
        if accountID == nil || notes != originalNotes { values["notes"] = notes }
        return values
    }

    var canSave: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !handle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (notes == originalNotes || notes.count <= 4000)
    }

    static func normalizedPlatform(_ value: String) -> String {
        ["rednote": "xiaohongshu", "google_business_profile": "google_business"][value] ?? value
    }

    static func platformName(_ value: String) -> String {
        ["xiaohongshu": "rednote", "rednote": "rednote", "instagram": "Instagram",
         "facebook": "Facebook", "tiktok": "TikTok", "youtube": "YouTube",
         "google_business": "Google 商家"][value] ?? value
    }
}

struct NativeAccountEditor: View {
    @ObservedObject var model: NativePublishingModel
    let onSaved: () async -> Void
    @Environment(\.presentationMode) private var presentation
    @State private var form: NativeAccountForm
    @State private var saving = false
    @State private var error: String?

    init(model: NativePublishingModel, initial: NativeAccountForm,
         onSaved: @escaping () async -> Void) {
        self.model = model
        self.onSaved = onSaved
        _form = State(initialValue: initial)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text(form.accountID == nil ? "关联账号" : "编辑账号档案")
                    .font(.system(size: 21, weight: .semibold))
                Spacer()
                Button("取消") { presentation.wrappedValue.dismiss() }
                    .keyboardShortcut(.cancelAction).disabled(saving)
                Button(saving ? "正在保存" : "保存") { save() }
                    .keyboardShortcut("s", modifiers: .command)
                    .buttonStyle(.borderedProminent).tint(PublishingTheme.accent)
                    .disabled(!form.canSave || saving)
            }
            Divider()
            field("账号名称", value: $form.name)
            HStack(alignment: .top, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("平台").font(.headline)
                    Picker("平台", selection: $form.platform) {
                        ForEach(platforms, id: \.self) { platform in
                            Text(NativeAccountForm.platformName(platform)).tag(platform)
                        }
                    }.labelsHidden().disabled(form.accountID != nil)
                }.frame(width: 170, alignment: .leading)
                field("所属分组", value: $form.brand)
            }
            VStack(alignment: .leading, spacing: 8) {
                field("账号标识或主页链接", value: $form.handle)
                    .disabled(form.accountID != nil)
                if form.accountID != nil {
                    Text("已有账号身份保持不变").font(.caption)
                        .foregroundColor(PublishingTheme.muted)
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("备注").font(.headline)
                TextEditor(text: $form.notes).font(.system(size: 13))
                    .frame(minHeight: 120).padding(7)
                    .background(PublishingTheme.surface).cornerRadius(10)
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12)))
            }
            if let error = error {
                Text(error).foregroundColor(.orange).font(.callout).textSelection(.enabled)
            }
            Text("档案保存后，可在官方后台登录").font(.caption)
                .foregroundColor(PublishingTheme.muted)
        }
        .padding(24).frame(width: 580)
        .background(Color(red: 0.07, green: 0.06, blue: 0.09))
        .preferredColorScheme(.dark)
    }

    private var platforms: [String] {
        let values = model.platforms.map(\.id)
        return values.contains(form.platform) ? values : [form.platform] + values
    }

    private func field(_ title: String, value: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            TextField(title, text: value).textFieldStyle(.roundedBorder)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }

    private func save() {
        saving = true
        error = nil
        Task {
            do {
                try await model.saveAccount(form)
                await onSaved()
                presentation.wrappedValue.dismiss()
            } catch { self.error = error.localizedDescription }
            saving = false
        }
    }
}
