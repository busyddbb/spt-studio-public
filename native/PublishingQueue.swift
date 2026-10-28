import AppKit
import Foundation

/// A small, persistent-queue client for the local publishing worker.  It only
/// claims work from localhost; the existing RednoteUploadCoordinator still
/// owns all WebKit and official-DOM operations.
@available(macOS 14.0, *)
final class PublishingQueueCoordinator {
    private struct QueueTask: Decodable {
        let queue_id: String
        let job: RednoteUploadJob
        let workspace: PublishingPayload
        let options: [String: JSONValue]
    }

    private struct ClaimResponse: Decodable { let tasks: [QueueTask] }

    private enum JSONValue: Decodable {
        case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if c.decodeNil() { self = .null }
            else if let v = try? c.decode(Bool.self) { self = .bool(v) }
            else if let v = try? c.decode(Double.self) { self = .number(v) }
            else if let v = try? c.decode(String.self) { self = .string(v) }
            else if let v = try? c.decode([String: JSONValue].self) { self = .object(v) }
            else { self = .array(try c.decode([JSONValue].self)) }
        }
        var any: Any {
            switch self {
            case .string(let v): return v
            case .number(let v): return v
            case .bool(let v): return v
            case .object(let v): return v.mapValues { $0.any }
            case .array(let v): return v.map { $0.any }
            case .null: return NSNull()
            }
        }
    }

    private let executorID = "native-" + UUID().uuidString.lowercased()
    private var worker: RednoteUploadCoordinator!
    private var timer: Timer?
    private var claiming = false
    private var activeQueueIDs = Set<String>()
    private var activeAccounts = Set<String>()
    private var accountByQueueID: [String: String] = [:]
    private var queueByJobID: [String: String] = [:]
    private var snapshotInFlight = false

    /// `onChange` is also called for ordinary upload states so the existing UI
    /// can keep displaying progress.  Queue events are persisted independently.
    init(onChange: @escaping (String, String, String) -> Void,
         onNeedsLogin: @escaping (String, String) -> Void) {
        worker = RednoteUploadCoordinator(onChange: { [weak self] jobID, state, message in
            onChange(jobID, state, message)
            guard let self, let queueID = self.queueByJobID[jobID] else { return }
            self.sendEvent(queueID: queueID, jobID: jobID, event: state, message: message)
        }, onNeedsLogin: onNeedsLogin)
    }

    convenience init() {
        self.init(onChange: { _, _, _ in }, onNeedsLogin: { _, _ in })
    }

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.poll() }
        poll()
    }

    func stop() { timer?.invalidate(); timer = nil }

    func preview(queueID: String, parentWindow: NSWindow, onReturn: @escaping () -> Void) -> NSView? {
        guard let jobID = queueByJobID.first(where: { $0.value == queueID })?.key else {
            sendEvent(queueID: queueID, event: "needs_attention", message: "任务不在当前进程中，请先核对后台记录，勿直接重传。")
            return nil
        }
        return worker.preview(jobID: jobID, parentWindow: parentWindow, onReturn: onReturn)
    }

    func cancel(queueID: String) {
        guard let jobID = queueByJobID.first(where: { $0.value == queueID })?.key else {
            sendAction("queue_cancel", arguments: ["id": queueID, "executor_id": executorID])
            return
        }
        sendAction("queue_cancel", arguments: ["id": queueID, "executor_id": executorID]) { [weak self] (result: Result<EmptyResponse, Error>) in
            guard case .success = result else { return }
            self?.worker.cancel(jobID: jobID)
        }
    }

    private func poll() {
        guard !claiming else { return }
        claiming = true
        // claim performs the stale-owner check atomically; an extra full
        // snapshot on every tick would duplicate database work.
        claim { [weak self] in self?.claiming = false }
    }

    private func getSnapshot(completion: @escaping () -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8766/api/publishing/queue")!)
        request.timeoutInterval = 10
        URLSession.shared.dataTask(with: request) { _, _, _ in
            DispatchQueue.main.async { completion() }
        }.resume()
    }

    private func claim(completion: @escaping () -> Void) {
        sendAction("queue_claim", arguments: ["executor_id": executorID]) { [weak self] (result: Result<ClaimResponse, Error>) in
            guard let self else { completion(); return }
            guard case .success(let response) = result else { completion(); return }
            for task in response.tasks {
                // The backend only hands out freshly queued tasks: one we still hold was retried, so let it go first.
                if self.activeQueueIDs.contains(task.queue_id) { self.release(queueID: task.queue_id, jobID: task.job.id) }
                guard !self.activeQueueIDs.contains(task.queue_id),
                      !self.activeAccounts.contains(task.job.account_id),
                      task.job.target == "image" || task.job.target == "video",
                      task.workspace.account.platform == "xiaohongshu" else {
                    if task.job.target != "image" && task.job.target != "video" {
                        self.sendEvent(queueID: task.queue_id, jobID: task.job.id, event: "needs_attention", message: "当前后台仅支持 rednote 图文组和单视频。")
                    }
                    continue
                }
                self.activeQueueIDs.insert(task.queue_id)
                self.activeAccounts.insert(task.job.account_id)
                self.accountByQueueID[task.queue_id] = task.job.account_id
                self.queueByJobID[task.job.id] = task.queue_id
                self.sendEvent(queueID: task.queue_id, jobID: task.job.id, event: "checking_login", message: "已由本机后台执行器领取，正在核对账号会话。")
                // The worker re-loads the authoritative workspace and fingerprint
                // before handing files to the official chooser.  No submit click
                // is implicit; an explicit submit intent must be implemented by
                // the UI/backend before it can be acted on.
                let options = task.options.mapValues { $0.any }
                self.worker.startClaimed(job: task.job, workspace: task.workspace,
                                         queueID: task.queue_id, options: options) { [weak self] event, message, evidence, noteID, url, completion in
                    guard let self else { completion(false); return }
                    var args: [String: Any] = ["id": task.queue_id, "event": event, "message": message, "executor_id": self.executorID]
                    if let evidence {
                        args["evidence"] = evidence
                        if let publishedAt = evidence["published_at"] { args["published_at"] = publishedAt }
                        if let basis = evidence["basis"] ?? evidence["published_at_basis"] { args["basis"] = basis }
                    }
                    if let noteID { args["note_id"] = noteID }
                    if let url, var components = URLComponents(string: url) { components.query = nil; components.fragment = nil; args["url"] = components.url?.absoluteString }
                    if event == "submit_intent" {
                        self.sendAction("queue_event", arguments: args) { (result: Result<QueueEventResponse, Error>) in
                            if case .success(let response) = result { completion(response.submit_granted == true) } else { completion(false) }
                        }
                    } else {
                        self.sendAction("queue_event", arguments: args) { (result: Result<EmptyResponse, Error>) in
                            if case .success = result {
                                completion(true)
                                // Keep attention/unknown sessions reachable for
                                // the explicit preview action. Their account
                                // lock remains in the persistent queue.
                                if ["published", "under_review", "failed", "cancelled"].contains(event) {
                                    self.sendAction("update_upload", arguments: ["id": task.job.id, "state": "cancelled", "message": "队列终态已记录；平台结果以队列回查为准."]) { (legacy: Result<EmptyResponse, Error>) in
                                        if case .success = legacy { self.release(queueID: task.queue_id, jobID: task.job.id) }
                                    }
                                }
                            } else { completion(false) }
                        }
                    }
                }
            }
            completion()
        }
    }

    private func release(queueID: String, jobID: String) {
        activeQueueIDs.remove(queueID)
        if let account = accountByQueueID.removeValue(forKey: queueID) { activeAccounts.remove(account) }
        queueByJobID.removeValue(forKey: jobID)
    }

    private func sendEvent(queueID: String, jobID: String? = nil, event: String, message: String) {
        var args: [String: Any] = ["id": queueID, "event": event, "message": message, "executor_id": executorID]
        if let jobID { args["job_id"] = jobID }
        sendAction("queue_event", arguments: args)
    }

    private func sendAction<T: Decodable>(_ action: String, arguments: [String: Any], completion: ((Result<T, Error>) -> Void)? = nil) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8766/api/publishing/action")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": action, "arguments": arguments])
        URLSession.shared.dataTask(with: request) { data, response, error in
            let result: Result<T, Error>
            do {
                if let error { throw error }
                guard let data, let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                    throw PublishingAPI.failure("本地发布队列暂时不可用。")
                }
                result = .success(try JSONDecoder().decode(T.self, from: data))
            } catch { result = .failure(error) }
            if let completion { DispatchQueue.main.async { completion(result) } }
        }.resume()
    }

    private func sendAction(_ action: String, arguments: [String: Any], completion: (() -> Void)? = nil) {
        sendAction(action, arguments: arguments) { (_: Result<EmptyResponse, Error>) in completion?() }
    }

    private struct EmptyResponse: Decodable {}
    private struct QueueEventResponse: Decodable { let submit_granted: Bool? }
}
