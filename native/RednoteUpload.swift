import AppKit
import WebKit
import UniformTypeIdentifiers

struct RednoteUploadJob: Decodable {
    let id: String
    let account_id: String
    let draft_id: String
    let fingerprint: String
    let target: String
    let state: String
    let message: String
}

private struct RednoteUploadContext: Decodable {
    let job: RednoteUploadJob
    let workspace: PublishingPayload
}

fileprivate struct RednoteQueueConfiguration {
    let queueID: String
    let options: [String: Any]
    let onEvent: (String, String, [String: Any]?, String?, String?, @escaping (Bool) -> Void) -> Void
}

private enum RednoteUploadAPI {
    static func prepare(accountID: String, draftID: String,
                        completion: @escaping (Result<RednoteUploadContext, Error>) -> Void) {
        request(action: "prepare_upload", arguments: ["account_id": accountID, "draft_id": draftID], completion: completion)
    }

    static func load(_ identifier: String, completion: @escaping (Result<RednoteUploadContext, Error>) -> Void) {
        var url = URLComponents(string: "http://127.0.0.1:8766/api/publishing/upload")!
        url.queryItems = [URLQueryItem(name: "id", value: identifier)]
        perform(URLRequest(url: url.url!), completion: completion)
    }

    static func update(_ identifier: String, state: String, message: String,
                       completion: @escaping (Result<[String: Any], Error>) -> Void) {
        request(action: "update_upload", arguments: ["id": identifier, "state": state, "message": message]) {
            (result: Result<EmptyUploadResponse, Error>) in
            completion(result.map { _ in [:] })
        }
    }

    private struct EmptyUploadResponse: Decodable {}

    private static func request<T: Decodable>(action: String, arguments: [String: Any],
                                              completion: @escaping (Result<T, Error>) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8766/api/publishing/action")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": action, "arguments": arguments])
        perform(request, completion: completion)
    }

    private static func perform<T: Decodable>(_ original: URLRequest,
                                              completion: @escaping (Result<T, Error>) -> Void) {
        var request = original
        request.timeoutInterval = 20
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { data, response, error in
            let result: Result<T, Error>
            do {
                if let error = error { throw error }
                guard let data = data, let http = response as? HTTPURLResponse else {
                    throw PublishingAPI.failure("无法读取上传任务。")
                }
                guard (200...299).contains(http.statusCode) else {
                    let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    throw PublishingAPI.failure(body?["error"] as? String ?? "上传任务未能继续。")
                }
                result = .success(try JSONDecoder().decode(T.self, from: data))
            } catch { result = .failure(error) }
            DispatchQueue.main.async { completion(result) }
        }.resume()
    }
}

/// Only public DOM controls are used. No platform requests or credentials are read.
enum RednoteUploadDOM {
    static func queueStep(options: [String: Any], title: String, body: String,
                          mediaNames: [String], phase: String) -> String {
        // The workspace copy of the page script, when present, wins over the bundled one, so a script fix needs no rebuild.
        let root = Bundle.main.object(forInfoDictionaryKey: "MediaDeskWorkspaceRoot") as? String
        let onDisk = root.map { URL(fileURLWithPath: $0).appendingPathComponent("native/PublishingQueueDOM.js") }
        let resource = onDisk.flatMap { FileManager.default.isReadableFile(atPath: $0.path) ? $0 : nil } ?? Bundle.main.url(forResource: "PublishingQueueDOM", withExtension: "js")
        guard let resource,
              let script = try? String(contentsOf: resource, encoding: .utf8),
              let data = try? JSONSerialization.data(withJSONObject: ["options": options, "title": title,
                        "body": body, "mediaNames": mediaNames, "phase": phase]),
              let arguments = String(data: data, encoding: .utf8) else {
            return "({status:'attention',reason:'后台发布资源不可用'})"
        }
        return "(" + script + ")(" + arguments + ")"
    }
    private static func quote(_ value: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [value])
        let array = String(data: data, encoding: .utf8)!
        return "(" + array + ")[0]"
    }

    private static func candidates(_ target: String) -> String {
        let image = target == "image" ? "true" : "false"
        return """
        const image = \(image);
        const candidates = Array.from(document.querySelectorAll('input.upload-input[type="file"]')).filter(el => {
          const accept = (el.accept || '').toLowerCase();
          const types = accept.split(',').map(item => item.trim());
          return image ? el.multiple && types.some(type => ['image/*','image/jpeg','image/png','.jpg','.jpeg','.png'].includes(type))
                       : !el.multiple && types.some(type => ['video/*','video/mp4','video/quicktime','.mp4','.mov','.mkv','.flv','.f4v','.rm','.rmvb','.m4v','.mpg','.mpeg','.ts'].includes(type));
        });
        """
    }

    static func readiness(target: String) -> String {
        return """
        (() => {
          if (/\\/login(?:\\/|$)/.test(location.pathname)) return {status:'login'};
          if (document.querySelector('input[placeholder="手机号"],input[placeholder="验证码"]')) return {status:'login'};
          \(candidates(target))
          if (candidates.length > 1) return {status:'ambiguous'};
          if (candidates.length === 1) return {status:'ready'};
          return {status:'wait'};
        })()
        """
    }

    static func clickInput(target: String) -> String {
        """
        (() => {
          \(candidates(target))
          if (candidates.length !== 1) return {status:'ambiguous'};
          candidates[0].click();
          return {status:'requested'};
        })()
        """
    }

    static func fill(title: String, body: String) -> String {
        """
        (() => {
          if (/\\/login(?:\\/|$)/.test(location.pathname)) return {status:'login'};
          const titles = Array.from(document.querySelectorAll('input[placeholder="填写标题会有更多赞哦"],textarea[placeholder="填写标题会有更多赞哦"]'));
          const editors = Array.from(document.querySelectorAll('.ProseMirror[contenteditable="true"]'));
          if (titles.length > 1 || editors.length > 1) return {status:'ambiguous'};
          if (titles.length !== 1 || editors.length !== 1) return {status:'wait'};
          const title = titles[0], editor = editors[0];
          if (title.disabled || title.readOnly) return {status:'wait'};
          const requestedTitle = \(quote(title)), requestedBody = \(quote(body));
          const normalize = text => String(text).replace(/\\r\\n/g,'\\n').replace(/\\u00a0/g,' ').trim();
          if (title.maxLength > 0 && requestedTitle.length > title.maxLength) return {status:'too_long'};
          const previousBody = normalize(editor.innerText || editor.textContent || '');
          if ((title.value && title.value !== requestedTitle) || (previousBody && previousBody !== normalize(requestedBody))) return {status:'existing_content'};
          const proto = title.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(title, requestedTitle);
          title.dispatchEvent(new Event('input',{bubbles:true}));
          title.dispatchEvent(new Event('change',{bubbles:true}));
          if (previousBody !== normalize(requestedBody)) {
            editor.focus();
            const range = document.createRange(); range.selectNodeContents(editor);
            const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
            if (!document.execCommand('insertText',false,requestedBody)) return {status:'editor_rejected'};
            editor.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:requestedBody}));
          }
          // Read the editor like the preflight does: paragraphs and <br> are line breaks,
          // ProseMirror's trailing <br> inside a paragraph is not text.
          const read = n => n.nodeType === 3 ? n.textContent : n.tagName === 'BR' ? (/trailingBreak/.test(n.className || '') ? '' : '\\n') : Array.from(n.childNodes).map(read).join('') + (/^(P|DIV)$/.test(n.tagName) ? '\\n' : '');
          const bodyNow = normalize(read(editor));
          const wanted = normalize(requestedBody);
          const sameWords = bodyNow.replace(/\\n+/g, '\\n') === wanted.replace(/\\n+/g, '\\n');
          if (title.value !== requestedTitle) return {status:'editor_rejected', detail:'标题回读长度 ' + title.value.length + ' / 期望 ' + requestedTitle.length};
          if (bodyNow !== wanted && !sameWords) return {status:'editor_rejected', detail:'正文回读长度 ' + bodyNow.length + ' / 期望 ' + wanted.length + '，首个不同在第 ' + [...bodyNow].findIndex((c, i) => c !== wanted[i]) + ' 字'};
          return {status:'filled'};
        })()
        """
    }


}

@available(macOS 14.0, *)
final class RednoteUploadCoordinator {
    private var sessions: [String: RednoteUploadSession] = [:]
    private var startingAccounts = Set<String>()
    private let onChange: (String, String, String) -> Void
    private let onNeedsLogin: (String, String) -> Void
    private var queuedStarts: [String: RednoteQueueConfiguration] = [:]

    init(onChange: @escaping (String, String, String) -> Void,
         onNeedsLogin: @escaping (String, String) -> Void) {
        self.onChange = onChange
        self.onNeedsLogin = onNeedsLogin
    }

    func start(accountID: String, draftID: String) {
        if let existing = sessions.values.first(where: { $0.job.account_id == accountID && $0.job.draft_id == draftID && !$0.isTerminal }) {
            if existing.state == "needs_login" { existing.resumeAfterLogin() }
            else { onChange(existing.job.id, existing.state, existing.message) }
            return
        }
        guard !startingAccounts.contains(accountID) else { return }
        startingAccounts.insert(accountID)
        RednoteUploadAPI.prepare(accountID: accountID, draftID: draftID) { [weak self] result in
            guard let self = self else { return }
            self.startingAccounts.remove(accountID)
            switch result {
            case .failure(let error): self.onChange("", "needs_attention", error.localizedDescription)
            case .success(let context):
                do {
                    let key = "\(context.job.account_id)|\(context.job.draft_id)"
                    let config = self.queuedStarts.removeValue(forKey: key)
                    let session = try RednoteUploadSession(context: context, onChange: self.onChange,
                                                           onNeedsLogin: self.onNeedsLogin, queue: config)
                    self.sessions[context.job.id] = session
                    session.begin()
                } catch {
                    RednoteUploadAPI.update(context.job.id, state: "failed", message: error.localizedDescription) { _ in }
                    self.onChange(context.job.id, "failed", error.localizedDescription)
                }
            }
        }
    }

    func startQueued(accountID: String, draftID: String, queueID: String,
                     options: [String: Any],
                     onEvent: @escaping (String, String, [String: Any]?, String?, String?, @escaping (Bool) -> Void) -> Void) {
        let key = "\(accountID)|\(draftID)"
        queuedStarts[key] = RednoteQueueConfiguration(queueID: queueID, options: options, onEvent: onEvent)
        start(accountID: accountID, draftID: draftID)
    }

    func startClaimed(job: RednoteUploadJob, workspace: PublishingPayload,
                      queueID: String, options: [String: Any],
                      onEvent: @escaping (String, String, [String: Any]?, String?, String?, @escaping (Bool) -> Void) -> Void) {
        if let existing = sessions[job.id] {
            // A retried task re-uses its job id: the backend has re-issued it, so the old session steps aside.
            existing.abandon()
            sessions[job.id] = nil
        }
        do {
            let config = RednoteQueueConfiguration(queueID: queueID, options: options, onEvent: onEvent)
            let session = try RednoteUploadSession(context: RednoteUploadContext(job: job, workspace: workspace),
                                                    onChange: onChange, onNeedsLogin: onNeedsLogin, queue: config)
            sessions[job.id] = session
            session.begin()
        } catch {
            onChange(job.id, "needs_attention", error.localizedDescription)
            onEvent("needs_attention", error.localizedDescription, nil, nil, nil) { _ in }
        }
    }

    func cancel(jobID: String) {
        if let session = sessions[jobID] { session.cancel(); return }
        RednoteUploadAPI.update(jobID, state: "cancelled", message: "已停止本机任务，请先核对平台草稿。") { [weak self] result in
            switch result {
            case .success: self?.onChange(jobID, "cancelled", "已停止本机任务，请先核对平台草稿。")
            case .failure(let error): self?.onChange(jobID, "needs_attention", error.localizedDescription)
            }
        }
    }

    func preview(jobID: String, parentWindow: NSWindow, onReturn: @escaping () -> Void) -> NSView? {
        guard let session = sessions[jobID] else {
            onChange(jobID, "needs_attention", "这次上传页面不在当前软件进程中，请先检查平台草稿，勿直接重传。")
            return nil
        }
        return session.preview(parentWindow: parentWindow, onReturn: onReturn)
    }
}

@available(macOS 14.0, *)
private final class RednoteUploadSession: NSObject, WKNavigationDelegate, WKUIDelegate {
    let job: RednoteUploadJob
    private let original: PublishingPayload
    private let onChange: (String, String, String) -> Void
    private let onNeedsLogin: (String, String) -> Void
    private let queue: RednoteQueueConfiguration?
    private let webView: WKWebView
    private var timer: Timer?
    private var deadline = Date()
    private var expectedChooser = false
    private var chooserDelivered = false
    private var stopped = false
    private var polling = false
    private weak var previewHost: NSWindow?
    private var previewView: RednoteUploadPreview?
    private var queueSubmitIntentSent = false
    private var checkingQueueResult = false
    private var clickISO: String?
    private var resultRecord: [String: Any]?
    private var duplicateChecked = false
    private var accountIdentityVerified = false
    private var queuePhase = "duplicate"
    private var queueProof: [String: Any]?
    private var queueUploadComplete = false
    private var lastHeartbeat = Date.distantPast
    private var lastWait = ""
    private var clickWaits = 0
    private var stage = ""
    private var stageStarted = Date()
    private var stageTimer: Timer?
    private var queueStarted: Date?
    private(set) var state: String
    private(set) var message: String
    var isTerminal: Bool { ["failed", "cancelled", "interrupted"].contains(state) }

    init(context: RednoteUploadContext, onChange: @escaping (String, String, String) -> Void,
         onNeedsLogin: @escaping (String, String) -> Void,
         queue: RednoteQueueConfiguration? = nil) throws {
        guard let identifier = UUID(uuidString: context.workspace.profile_id),
              context.workspace.account.platform == "xiaohongshu",
              let draft = context.workspace.draft,
              draft.fingerprint == context.job.fingerprint else {
            throw PublishingAPI.failure("上传任务与当前内容不一致。")
        }
        job = context.job
        original = context.workspace
        state = context.job.state
        message = context.job.message
        self.onChange = onChange
        self.onNeedsLogin = onNeedsLogin
        self.queue = queue
        let configuration = WKWebViewConfiguration()
        RednoteBrowserIdentity.apply(to: configuration)
        configuration.websiteDataStore = RednoteSessionVault.shared.dataStore(profile: identifier)
        configuration.userContentController = WKUserContentController()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = [.audio, .video]
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 850), configuration: configuration)
        super.init()
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsLinkPreview = false
    }

    /// Before any page is polled, a stage heartbeat keeps the queue informed and bounds a hung restore or login check.
    private func enterStage(_ name: String) {
        stage = name
        stageStarted = Date()
        if stageTimer == nil, queue != nil {
            stageTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
                guard let self, !self.stopped else { self?.stageTimer?.invalidate(); self?.stageTimer = nil; return }
                if Date().timeIntervalSince(self.stageStarted) > 150 {
                    self.attention("\(self.stage)超时，未开始上传；请检查网络或登录后重试。")
                    return
                }
                self.queue?.onEvent("checking_login", "后台任务仍在运行。（\(self.stage)）", nil, nil, nil) { _ in }
            }
        }
    }

    /// The backend re-issued this job to a new session; this one must not keep running beside it.
    func abandon() {
        stopped = true
        stopPolling()
        stageTimer?.invalidate(); stageTimer = nil
        webView.stopLoading()
    }

    func begin() {
        guard let profile = UUID(uuidString: original.profile_id) else { attention("账号会话配置无效。"); return }
        enterStage("恢复账号会话")
        RednoteSessionVault.shared.prepare(profile: profile, onError: { [weak self] message in
            guard let self = self, !self.stopped else { return }
            self.message = message
            self.previewView?.setStatus(message)
            self.onChange(self.job.id, "needs_attention", message)
        }, completion: { [weak self] _ in
            guard let self = self, !self.stopped else { return }
            self.beginAfterSessionRestore()
        })
    }

    private func beginAfterSessionRestore() {
        enterStage("核对登录状态")
        revalidate { [weak self] _ in
            guard let self = self else { return }
            self.transition("checking_login", "正在核对rednote账号与已有笔记", completion: { [weak self] in
                guard let self = self else { return }
                self.enterStage("打开笔记管理页")
                if self.queue != nil {
                    self.webView.load(URLRequest(url: URL(string: "https://creator.rednote.com/new/note-manager")!))
                } else {
                    self.loadPublishPage()
                }
            })
        }
    }

    private func loadPublishPage() {
        var url = URLComponents(string: "https://creator.rednote.com/publish/publish")!
        url.queryItems = [URLQueryItem(name: "from", value: "menu"), URLQueryItem(name: "target", value: self.job.target)]
        webView.load(URLRequest(url: url.url!))
        startPolling(editor: false)
    }

    func resumeAfterLogin() {
        guard state == "needs_login" else { return }
        stopped = false
        chooserDelivered = false
        begin()
    }

    func cancel() {
        stopped = true
        expectedChooser = false
        stopPolling()
        webView.stopLoading()
        transition("cancelled", "已停止本机任务；请先核对平台草稿。")
    }

    func preview(parentWindow: NSWindow, onReturn: @escaping () -> Void) -> NSView {
        previewHost = parentWindow
        if let view = previewView { view.onReturn = onReturn; return view }
        let view = RednoteUploadPreview(webView: webView, account: original.account.name, onReturn: onReturn)
        view.setStatus(message)
        previewView = view
        return view
    }

    private func revalidate(onFailure: (() -> Void)? = nil, _ completion: @escaping (PublishingPayload) -> Void) {
        guard !stopped else { onFailure?(); return }
        RednoteUploadAPI.load(job.id) { [weak self] result in
            guard let self = self, !self.stopped else { onFailure?(); return }
            switch result {
            case .failure(let error): self.attention(error.localizedDescription); onFailure?()
            case .success(let current):
                if current.job.state == "cancelled" { self.cancel(); onFailure?(); return }
                guard current.job.id == self.job.id,
                      current.job.account_id == self.job.account_id,
                      current.job.draft_id == self.job.draft_id,
                      current.job.fingerprint == self.job.fingerprint,
                      current.job.target == self.job.target,
                      current.workspace.account.id == self.original.account.id,
                      current.workspace.profile_id == self.original.profile_id,
                      current.workspace.can_upload_current,
                      current.workspace.draft?.fingerprint == self.job.fingerprint,
                      current.workspace.media.map(\.id) == self.original.media.map(\.id),
                      current.workspace.media.allSatisfy(\.available) else {
                    self.attention("内容、素材或核对状态已变化，请回工作台重新核对。")
                    onFailure?()
                    return
                }
                completion(current.workspace)
            }
        }
    }

    private func transition(_ next: String, _ text: String, onFailure: (() -> Void)? = nil, completion: (() -> Void)? = nil) {
        state = next
        message = text
        previewView?.setStatus(text)
        RednoteUploadAPI.update(job.id, state: next, message: text) { [weak self] result in
            guard let self = self else { onFailure?(); return }
            switch result {
            case .success:
                guard self.state == next else { onFailure?(); return }
                self.onChange(self.job.id, next, text)
                if !self.stopped || ["cancelled", "needs_login"].contains(next) { completion?() }
                else { onFailure?() }
            case .failure(let error):
                self.stopped = true
                self.stopPolling()
                self.state = "needs_attention"
                self.message = error.localizedDescription
                self.previewView?.setStatus(error.localizedDescription)
                self.onChange(self.job.id, "needs_attention", error.localizedDescription)
                onFailure?()
            }
        }
    }

    private func attention(_ text: String, beforeClick: Bool = false) {
        stopped = true
        stopPolling()
        stageTimer?.invalidate(); stageTimer = nil
        webView.stopLoading()
        expectedChooser = false
        transition("needs_attention", text)
        queue?.onEvent(queueSubmitIntentSent && !beforeClick ? "unknown" : "needs_attention", text, nil, nil, nil) { _ in }
    }

    private func requireLogin() {
        if let profile = UUID(uuidString: original.profile_id) {
            RednoteSessionVault.shared.rejectSession(profile: profile)
        }
        guard state != "needs_login" else { return }
        if chooserDelivered {
            attention("素材已交给平台后登录失效，请先检查原平台草稿；软件不会自动重传。")
            return
        }
        stopped = true
        stopPolling()
        expectedChooser = false
        transition("needs_login", "请先登录这个rednote账号，再继续上传。", completion: { [weak self] in
            guard let self = self else { return }
            self.onNeedsLogin(self.job.account_id, self.job.draft_id)
        })
    }

    private func startPolling(editor: Bool) {
        stopPolling()
        stageTimer?.invalidate(); stageTimer = nil
        if queue != nil {
            if queueStarted == nil { queueStarted = Date() }
            deadline = queueStarted!.addingTimeInterval(1800)
        } else { deadline = Date().addingTimeInterval(45) }
        timer = Timer.scheduledTimer(withTimeInterval: 0.8, repeats: true) { [weak self] _ in
            self?.poll(editor: editor)
        }
        poll(editor: editor)
    }

    private func stopPolling() { timer?.invalidate(); timer = nil; polling = false }

    private func poll(editor: Bool) {
        guard !stopped else { return }
        guard Date() < deadline else { attention("上传页面未准备好，请打开预览检查；软件不会自动重传。"); return }
        guard !polling else { return }
        let page = webView.url?.path ?? "(无页面)"
        if webView.isLoading { lastWait = "页面加载中 " + page }
        else if !permitted(webView.url) { lastWait = "页面不在允许范围 " + page }
        if let queue, Date().timeIntervalSince(lastHeartbeat) > 20 {
            lastHeartbeat = Date()
            let heartbeat = checkingQueueResult ? "checking_result" : (queueUploadComplete ? "processing" : (chooserDelivered ? "uploading" : "checking_login"))
            // The wait reason and page path make a stalled step diagnosable from the queue alone.
            queue.onEvent(heartbeat, "后台任务仍在运行。" + (lastWait.isEmpty ? "" : "（" + lastWait + " · " + page + "）"), nil, nil, nil) { _ in }
        }
        guard !webView.isLoading else { return }
        guard permitted(webView.url) else { return }
        if queue != nil, ["duplicate", "identity_open", "identity_verify", "preflight", "result", "result_verify"].contains(queuePhase) {
            pollQueueStep()
            return
        }
        polling = true
        let script = editor ? RednoteUploadDOM.fill(title: requestedTitle, body: requestedBody)
                            : RednoteUploadDOM.readiness(target: job.target)
        webView.evaluateJavaScript(script) { [weak self] value, error in
            guard let self = self, !self.stopped else { return }
            self.polling = false
            if error != nil { return }
            let result = value as? [String: Any]
            switch result?["status"] as? String {
            case "login": self.requireLogin()
            case "ready" where !editor: self.selectCurrentMedia()
            case "filled" where editor:
                if self.queue != nil { self.beginQueuePreflight() }
                else {
                    self.stopPolling()
                    self.transition("awaiting_review", "文案已填入，素材已交给官方上传控件。请核对平台预览后发布。")
                }
            case "processing" where editor:
                if self.state != "uploading" {
                    self.queue?.onEvent("processing", "平台正在处理视频或素材，请等待官方处理完成。", nil, nil, self.webView.url?.absoluteString) { _ in }
                    self.message = "平台正在处理视频或素材，请等待官方处理完成。"
                    self.previewView?.setStatus(self.message)
                }
            case "ambiguous": self.attention("平台上传控件有多处匹配，请打开预览检查。")
            case "too_long": self.attention("标题超过平台当前上限，请回编辑器修改后重新核对。")
            case "existing_content": self.attention("平台编辑器已有其他内容，请打开预览核对，避免覆盖。")
            case "editor_rejected": self.attention("平台编辑器未完整接收文案，请打开预览核对。" + ((result?["detail"] as? String).map { "（" + $0 + "）" } ?? ""))
            default: break
            }
        }
    }

    private func queueOptions() -> (topics: [String], allowCopy: Bool, scheduled: Bool, submit: Bool, profileID: String?) {
        guard let options = queue?.options else { return ([], false, false, false, nil) }
        let topics: [String]
        if let values = options["topics"] as? [Any] { topics = values.compactMap { $0 as? String } }
        else if let value = options["topics"] as? String { topics = value.split { $0 == "," || $0 == "，" || $0 == "#" || $0 == "\n" }.map(String.init) }
        else { topics = [] }
        let allowCopy = (options["allow_body_copy"] as? Bool) ?? (options["copy_body"] as? Bool) ?? false
        let scheduled = (options["scheduled"] as? Bool) ?? ((options["scheduled_at"] as? String)?.isEmpty == false)
        let submit = (options["submit_enabled"] as? Bool) ?? false
        let profileID = options["expected_profile_id"] as? String
        return (topics.map { $0.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "#")) }.filter { !$0.isEmpty }, allowCopy, scheduled, submit, profileID)
    }

    private func beginQueuePreflight() {
        queuePhase = "preflight"
        pollQueueStep()
    }

    private var requestedTitle: String { queue?.options["title"] as? String ?? original.draft?.title ?? "" }
    private var requestedBody: String { queue?.options["body"] as? String ?? original.draft?.body ?? "" }

    private func stepOptions() -> [String: Any] {
        var options = queue?.options ?? [:]
        options["duplicate_checked"] = duplicateChecked
        if accountIdentityVerified, let expected = queueOptions().profileID {
            options["identity_proof"] = ["profile_id": expected]
        }
        if let resultRecord { options["result_record"] = resultRecord }
        return options
    }

    private func pollQueueStep() {
        guard !stopped, !polling, !webView.isLoading, let queue else { return }
        polling = true
        let script = RednoteUploadDOM.queueStep(options: stepOptions(), title: requestedTitle,
            body: requestedBody, mediaNames: original.media.sorted { $0.order < $1.order }.map { $0.name }, phase: queuePhase)
        webView.evaluateJavaScript(script) { [weak self] value, error in
            guard let self, !self.stopped else { return }
            self.polling = false
            guard error == nil, let result = value as? [String: Any], let status = result["status"] as? String else {
                self.attention("官方页面核验暂不可读；请打开预览核对，软件不会重传。")
                return
            }
            switch status {
            case "wait": self.lastWait = (result["reason"] as? String ?? "") + " [" + self.queuePhase + "]"
            case "media_processing":
                if result["upload_complete"] as? Bool == true {
                    self.queueUploadComplete = true
                    queue.onEvent("processing", "媒体已上传，平台正在处理。", nil, nil, nil) { _ in }
                }
            case "login": self.requireLogin()
            case "identity_opening" where self.queuePhase == "duplicate":
                // The DOM step has opened an existing public note only to establish
                // account identity. Never fill or submit while this phase is active.
                self.queuePhase = "identity_open"
            case "identity_note" where ["duplicate", "identity_open"].contains(self.queuePhase):
                guard let noteID = result["note_id"] as? String,
                      noteID.range(of: "^[a-f0-9]{24}$", options: .regularExpression) != nil,
                      let rawURL = result["url"] as? String,
                      let raw = URL(string: rawURL), self.permitted(raw),
                      raw.query == nil, raw.fragment == nil,
                      raw.path == "/discovery/item/\(noteID)" else {
                    self.attention("账号身份公开笔记链接无法安全核对，已停止。")
                    return
                }
                var components = URLComponents(url: raw, resolvingAgainstBaseURL: false)
                components?.query = nil
                components?.fragment = nil
                guard let publicURL = components?.url else {
                    self.attention("账号身份公开笔记链接无效，已停止。")
                    return
                }
                self.queuePhase = "identity_verify"
                self.webView.load(URLRequest(url: publicURL))
            case "identity_profile" where self.queuePhase == "identity_verify":
                // The public note route is dead; verify on the account's own public profile instead.
                guard let expected = self.queueOptions().profileID, let rawURL = result["url"] as? String,
                      let url = URL(string: rawURL), self.permitted(url), url.query == nil, url.fragment == nil,
                      url.path == "/user/profile/\(expected)" else {
                    self.attention("账号公开主页链接无法安全核对，已停止。")
                    return
                }
                self.lastWait = "核验公开主页"
                self.webView.load(URLRequest(url: url))
            case "identity_verified" where self.queuePhase == "identity_verify":
                guard let verified = result["account_profile_id"] as? String,
                      let expected = self.queueOptions().profileID,
                      verified.caseInsensitiveCompare(expected) == .orderedSame else {
                    self.attention("公开笔记作者身份与目标账号不一致，已停止。")
                    return
                }
                self.accountIdentityVerified = true
                self.queuePhase = "duplicate"
                self.webView.load(URLRequest(url: URL(string: "https://creator.rednote.com/new/note-manager")!))
            case "duplicate": self.attention("该账号已有同标题笔记或草稿，已停止防止重复。")
            case "clear" where self.queuePhase == "duplicate":
                self.duplicateChecked = true
                self.queuePhase = "upload"
                self.loadPublishPage()
            case "proof" where self.queuePhase == "preflight":
                self.stopPolling()
                guard let proof = result["evidence"] as? [String: Any] else { self.attention("发布前证据缺失。"); return }
                self.queueProof = proof
                self.queueUploadComplete = true
                self.captureEvidence { shot in
                    var evidence = proof
                    if let shot { evidence.merge(shot) { _, next in next } }
                    self.queuePreflightPassed(evidence: evidence)
                }
            case "result_card" where self.queuePhase == "result":
                guard let edit = result["edit_url"] as? String, let url = URL(string: edit),
                      self.permitted(url), url.path == "/publish/update" else { self.attention("回查链接无效。"); return }
                self.resultRecord = result
                self.queuePhase = "result_verify"
                self.webView.load(URLRequest(url: url))
            case "result" where self.queuePhase == "result_verify":
                guard let proof = result["evidence"] as? [String: Any], proof["content_verified"] as? Bool == true,
                      let status = result["result_status"] as? String, ["published", "under_review"].contains(status),
                      let noteID = result["note_id"] as? String, let url = result["url"] as? String else {
                    self.attention("发布结果证据不完整。"); return
                }
                self.stopPolling()
                self.captureEvidence { shot in
                    var evidence = proof
                    if let shot { evidence.merge(shot) { _, next in next } }
                    evidence["published_at"] = self.clickISO
                    evidence["basis"] = "click_proxy"
                    evidence["verified_at"] = ISO8601DateFormatter().string(from: Date())
                    queue.onEvent(status, status == "published" ? "官方后台与内容回查确认已发布。" : "官方后台确认审核中。", evidence, noteID, url) { saved in
                        self.stopped = true
                        self.state = saved ? status : "unknown"
                        self.message = saved ? (status == "published" ? "已发布，发布记录已回写。" : "审核中，提交记录已回写。") : "平台结果已读到，但本地回写失败，请核对原笔记；勿重发。"
                        self.previewView?.setStatus(self.message)
                    }
                }
            default:
                self.attention(result["reason"] as? String ?? "官方页面控件无法核准，已停止。")
            }
        }
    }

    private func queuePreflightPassed(evidence: [String: Any]) {
        guard let queue else { return }
        queue.onEvent("preflight", "已核齐账号、媒体、完整文案、结构化话题和设置。", evidence, nil, nil) { [weak self] saved in
            guard let self, saved, !self.stopped else { self?.attention("预检证据未保存，已停止。"); return }
            guard self.queueOptions().submit else {
                self.attention("草稿已准备并核对，未授权自动提交。")
                return
            }
            // The evidence is already persisted. Do not resend a screenshot in the intent.
            queue.onEvent("submit_intent", "请求保存单次提交意图。", nil, nil, nil) { [weak self] granted in
                guard let self else { return }
                guard granted, !self.stopped, !self.queueSubmitIntentSent else {
                    self.attention("提交意图未获确认，已停止，未点击发布。")
                    return
                }
                self.queueSubmitIntentSent = true
                self.clickQueuePublish()
            }
        }
    }

    private func clickQueuePublish() {
        guard queueSubmitIntentSent, !stopped else { return }
        // Save the time before the sole click; a lost callback must never retry it.
        clickISO = ISO8601DateFormatter().string(from: Date())
        let script = RednoteUploadDOM.queueStep(options: stepOptions(), title: requestedTitle, body: requestedBody,
            mediaNames: original.media.sorted { $0.order < $1.order }.map { $0.name }, phase: "click")
        webView.evaluateJavaScript(script) { [weak self] value, error in
            guard let self, !self.stopped else { return }
            guard error == nil else {
                self.attention("发布按钮操作结果不明，请先回查原笔记；不会再次点击。")
                return
            }
            let result = value as? [String: Any]
            let status = result?["status"] as? String ?? ""
            let reason = result?["reason"] as? String ?? status
            // The step only reports "clicked" after the one click; any other answer was given before it.
            if status == "wait" {
                self.clickWaits += 1
                if self.clickWaits > 75 { self.attention("[未点击] 发布前核对超时：" + reason, beforeClick: true); return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in self?.clickQueuePublish() }
                return
            }
            guard status == "clicked" else {
                self.attention("[未点击] 发布前核对未通过：" + reason, beforeClick: true)
                return
            }
            self.checkingQueueResult = true
            self.queuePhase = "result"
            self.queue?.onEvent("checking_result", "已点击一次发布，正在核对实际结果。", nil, nil, nil) { _ in }
            self.startPolling(editor: false)
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
                guard let self, !self.stopped, self.queuePhase == "result",
                      self.webView.url?.path.contains("note-manager") != true else { return }
                self.webView.load(URLRequest(url: URL(string: "https://creator.rednote.com/new/note-manager")!))
            }
        }
    }

    private func captureEvidence(_ completion: @escaping ([String: Any]?) -> Void) {
        guard queue != nil else { completion(nil); return }
        webView.takeSnapshot(with: nil) { image, _ in
            guard let image, let tiff = image.tiffRepresentation,
                  let rep = NSBitmapImageRep(data: tiff),
                  let data = rep.representation(using: .png, properties: [:]), data.count < 4_000_000 else {
                completion(nil); return
            }
            completion(["png_base64": data.base64EncodedString()])
        }
    }

    private func selectCurrentMedia() {
        stopPolling()
        revalidate { [weak self] _ in
            self?.transition("selecting_media", "正在选择本条素材", completion: { [weak self] in
                guard let self = self, !self.stopped else { return }
                self.expectedChooser = true
                self.webView.evaluateJavaScript(RednoteUploadDOM.clickInput(target: self.job.target)) { [weak self] value, error in
                    guard let self = self, !self.stopped else { return }
                    if error != nil || (value as? [String: Any])?["status"] as? String != "requested" {
                        self.attention("未能打开平台上传控件，请打开预览检查。")
                    }
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
                    guard let self = self, self.expectedChooser, !self.stopped else { return }
                    self.attention("平台没有接受素材选择，请打开预览检查。")
                }
            })
        }
    }

    private func publicHTTPS(_ url: URL?) -> Bool {
        guard let url = url, url.scheme == "https", url.user == nil, url.password == nil,
              url.port == nil || url.port == 443, let host = url.host?.lowercased(),
              !host.isEmpty, host != "localhost", !host.contains(":"),
              host.range(of: "^[0-9.]+$", options: .regularExpression) == nil,
              ![".localhost", ".local", ".lan", ".internal", ".home.arpa"].contains(where: host.hasSuffix) else { return false }
        return true
    }

    private func permitted(_ url: URL?) -> Bool {
        guard publicHTTPS(url), let host = url?.host?.lowercased() else { return false }
        return original.platform.allowed_domains.contains { host == $0 || host.hasSuffix("." + $0) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.targetFrame?.isMainFrame == false {
            decisionHandler(publicHTTPS(action.request.url) ? .allow : .cancel)
        } else { decisionHandler(permitted(action.request.url) ? .allow : .cancel) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, (response.response as? HTTPURLResponse)?.statusCode == 401,
           let profile = UUID(uuidString: original.profile_id) {
            RednoteSessionVault.shared.rejectSession(profile: profile)
        }
        let safe = response.isForMainFrame ? permitted(response.response.url) : publicHTTPS(response.response.url)
        decisionHandler(safe && response.canShowMIMEType ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if permitted(action.request.url) { webView.load(action.request) }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if webView.url?.path.contains("/login") == true && !stopped { requireLogin(); return }
        if queue != nil, ["duplicate", "identity_open", "identity_verify", "result", "result_verify"].contains(queuePhase), !stopped {
            startPolling(editor: false)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled && !stopped { attention("rednote页面未能加载，请打开预览检查。") }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard frame.isMainFrame, permitted(webView.url), permitted(frame.request.url) else { completionHandler(nil); return }
        if !expectedChooser {
            choosePreviewFiles(multiple: parameters.allowsMultipleSelection, completion: completionHandler)
            return
        }
        expectedChooser = false
        guard parameters.allowsMultipleSelection || original.media.count == 1 else {
            completionHandler(nil); attention("当前平台控件每次只接受一个文件，请打开预览核对。"); return
        }
        revalidate(onFailure: { completionHandler(nil) }) { [weak self] current in
            guard let self = self, !self.stopped, self.permitted(self.webView.url) else { completionHandler(nil); return }
            self.transition("uploading", "正在交接素材给官方上传控件", onFailure: { completionHandler(nil) }) { [weak self] in
                guard let self = self, !self.stopped else { completionHandler(nil); return }
                self.chooserDelivered = true
                completionHandler(current.media.sorted { $0.order < $1.order }.map { URL(fileURLWithPath: $0.path) })
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.startPolling(editor: true) }
            }
        }
    }

    private func choosePreviewFiles(multiple: Bool, completion: @escaping ([URL]?) -> Void) {
        guard let host = previewHost else { completion(nil); attention("平台需要手动选文件，请打开预览。"); return }
        let panel = NSOpenPanel()
        panel.title = "选择素材"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = multiple
        panel.allowedContentTypes = [.image, .movie]
        panel.beginSheetModal(for: host) { [weak self] response in
            guard let self = self, self.permitted(self.webView.url) else { completion(nil); return }
            completion(response == .OK ? panel.urls : nil)
        }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        attention("平台有提示需要处理，请打开预览。")
        guard let host = previewHost else { completionHandler(); return }
        let alert = NSAlert(); alert.messageText = "rednote"; alert.informativeText = message
        alert.addButton(withTitle: "知道了")
        alert.beginSheetModal(for: host) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard let host = previewHost else { attention("平台需要确认，请打开预览。"); completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = "rednote"; alert.informativeText = message
        alert.addButton(withTitle: "确定"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: host) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
}

private final class RednoteUploadPreview: NSView {
    var onReturn: () -> Void
    private let status = NSTextField(labelWithString: "")

    init(webView: WKWebView, account: String, onReturn: @escaping () -> Void) {
        self.onReturn = onReturn
        super.init(frame: .zero)
        let toolbar = NSStackView()
        toolbar.orientation = .horizontal
        toolbar.spacing = 10
        let back = NSButton(title: "返回", target: self, action: #selector(returnToWorkspace))
        back.bezelStyle = .rounded
        toolbar.addArrangedSubview(back)
        let label = NSTextField(labelWithString: account)
        label.font = .systemFont(ofSize: 13, weight: .semibold)
        toolbar.addArrangedSubview(label)
        let spacer = NSView(); spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        toolbar.addArrangedSubview(spacer)
        toolbar.addArrangedSubview(NSTextField(labelWithString: "creator.rednote.com"))
        status.font = .systemFont(ofSize: 11)
        status.textColor = .secondaryLabelColor
        status.lineBreakMode = .byTruncatingTail
        for child in [toolbar, status, webView] as [NSView] { addSubview(child); child.translatesAutoresizingMaskIntoConstraints = false }
        NSLayoutConstraint.activate([
            toolbar.topAnchor.constraint(equalTo: topAnchor, constant: 8),
            toolbar.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            toolbar.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            toolbar.heightAnchor.constraint(equalToConstant: 30),
            status.topAnchor.constraint(equalTo: toolbar.bottomAnchor, constant: 4),
            status.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 13),
            status.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -13),
            webView.topAnchor.constraint(equalTo: status.bottomAnchor, constant: 7),
            webView.leadingAnchor.constraint(equalTo: leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: bottomAnchor)
        ])
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func setStatus(_ text: String) { status.stringValue = text }
    @objc private func returnToWorkspace() { onReturn() }
}
