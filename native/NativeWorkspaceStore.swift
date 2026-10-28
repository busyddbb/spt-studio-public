import Foundation
import Combine

/// The local API keeps unknown values as JSON null, rather than inventing zeroes.
enum WorkspaceJSON: Codable, Equatable, Sendable {
    case object([String: WorkspaceJSON])
    case array([WorkspaceJSON])
    case string(String)
    case number(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let decoded = try? value.decode(Bool.self) { self = .bool(decoded) }
        else if let decoded = try? value.decode(String.self) { self = .string(decoded) }
        else if let decoded = try? value.decode(Double.self) { self = .number(decoded) }
        else if let decoded = try? value.decode([WorkspaceJSON].self) { self = .array(decoded) }
        else { self = .object(try value.decode([String: WorkspaceJSON].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self {
        case .object(let decoded): try value.encode(decoded)
        case .array(let decoded): try value.encode(decoded)
        case .string(let decoded): try value.encode(decoded)
        case .number(let decoded): try value.encode(decoded)
        case .bool(let decoded): try value.encode(decoded)
        case .null: try value.encodeNil()
        }
    }

    subscript(_ key: String) -> WorkspaceJSON { object[key] ?? .null }
    var object: [String: WorkspaceJSON] {
        if case .object(let value) = self { return value }
        return [:]
    }
    var array: [WorkspaceJSON] {
        if case .array(let value) = self { return value }
        return []
    }
    var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }
    var number: Double? {
        if case .number(let value) = self { return value }
        return nil
    }
    var bool: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }
}

struct WorkspaceRecord: Identifiable, Equatable, Sendable {
    let raw: WorkspaceJSON
    var id: String { raw["id"].string ?? "" }
    subscript(_ key: String) -> WorkspaceJSON { raw[key] }
}

enum NativeWorkspaceError: LocalizedError, Equatable {
    case message(String)
    var errorDescription: String? {
        if case .message(let text) = self { return text }
        return nil
    }
}

private final class WorkspaceNoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

/// Native controls use the same loopback service, without a browser or its cookies.
@MainActor
final class NativeWorkspaceStore: ObservableObject {
    @Published private(set) var accounts: [WorkspaceRecord] = []
    @Published private(set) var posts: [WorkspaceRecord] = []
    @Published private(set) var works: [WorkspaceRecord] = []
    @Published private(set) var historyPosts: [WorkspaceRecord] = []
    @Published private(set) var intelligence: WorkspaceJSON = .null
    @Published private(set) var health: WorkspaceJSON = .null
    @Published private(set) var loading = false
    @Published private(set) var error: String?

    private struct Snapshot {
        let dashboard: WorkspaceJSON
        let works: WorkspaceJSON
        let health: WorkspaceJSON
    }

    private static let origin = "http://127.0.0.1:8766"
    private let session: URLSession
    private var reloadTask: Task<Void, Never>?
    private var reloadID: UUID?
    private var indexing = false

    init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        configuration.waitsForConnectivity = false
        session = URLSession(configuration: configuration,
                             delegate: WorkspaceNoRedirect(), delegateQueue: nil)
    }

    /// Concurrent views share one read; all three responses publish atomically.
    func reload() async {
        if let current = reloadTask {
            await current.value
            return
        }
        loading = true
        error = nil
        let identifier = UUID()
        reloadID = identifier
        let task = Task { [weak self] in
            guard let self = self else { return }
            defer {
                if self.reloadID == identifier {
                    self.reloadTask = nil
                    self.reloadID = nil
                    self.loading = false
                }
            }
            do { try self.apply(await self.readSnapshot()) }
            catch { self.error = self.readableError(error) }
        }
        reloadTask = task
        await task.value
    }

    func detail(id: String) async throws -> WorkspaceJSON {
        guard validIdentifier(id) else {
            throw NativeWorkspaceError.message("作品编号不正确。")
        }
        do { return try await request("/api/spt/works/" + id) }
        catch { throw NativeWorkspaceError.message(readableError(error)) }
    }

    func reindex() async {
        guard !indexing else { return }
        indexing = true
        defer { indexing = false }
        do {
            _ = try await request("/api/spt/reindex", method: "POST")
            if let current = reloadTask { await current.value }
            await reload()
        } catch { self.error = readableError(error) }
    }

    /// Only original work files and cached covers may be handed to media controls.
    func localURL(_ path: String) -> URL? {
        guard let parts = URLComponents(string: path),
              parts.user == nil, parts.password == nil, parts.fragment == nil,
              !path.contains("\\"), !containsControl(path) else { return nil }
        if parts.scheme != nil {
            guard parts.scheme == "http", parts.host == "127.0.0.1",
                  parts.port == 8766 else { return nil }
        } else if parts.host != nil || !path.hasPrefix("/") || path.hasPrefix("//") {
            return nil
        }
        var normalized = parts
        if normalized.path.hasPrefix("/api/works/") {
            normalized.path = "/api/spt" + normalized.path.dropFirst(4)
        }
        guard normalized.path.hasPrefix("/api/spt/works/"),
              safeRelativePath(normalized.path, allowLeadingSlash: true) else { return nil }
        for item in normalized.queryItems ?? [] where item.name == "path" {
            guard let value = item.value, !value.hasPrefix("/"),
                  safeRelativePath(value) else { return nil }
        }
        normalized.scheme = "http"
        normalized.host = "127.0.0.1"
        normalized.port = 8766
        return normalized.url
    }

    private func readSnapshot() async throws -> Snapshot {
        async let dashboard = request("/api/spt/dashboard")
        async let works = request("/api/spt/works")
        async let health = request("/api/spt/health")
        return try await Snapshot(dashboard: dashboard, works: works, health: health)
    }

    private func apply(_ snapshot: Snapshot) throws {
        guard snapshot.health["app"].string == "spt" else {
            throw NativeWorkspaceError.message("当前本地服务不是作品工作区。")
        }
        let newAccounts = try records(snapshot.dashboard["accounts"])
        let newPosts = try records(snapshot.dashboard["posts"])
        let newWorks = try records(snapshot.works["works"])
        let newHistory = try records(snapshot.dashboard["history_posts"])
        accounts = newAccounts
        posts = newPosts
        works = newWorks
        historyPosts = newHistory
        intelligence = snapshot.dashboard["intelligence"]
        health = snapshot.health
    }

    private func records(_ value: WorkspaceJSON) throws -> [WorkspaceRecord] {
        guard case .array(let values) = value,
              values.allSatisfy({ validIdentifier($0["id"].string ?? "") }) else {
            throw NativeWorkspaceError.message("本地资料格式不完整，请重读资料。")
        }
        return values.map { WorkspaceRecord(raw: $0) }
    }

    private func request(_ path: String, method: String = "GET") async throws -> WorkspaceJSON {
        guard let url = URL(string: Self.origin + path) else {
            throw NativeWorkspaceError.message("本地资料地址无效。")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Self.origin, forHTTPHeaderField: "Origin")
        if method == "POST" {
            request.httpBody = Data("{}".utf8)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw NativeWorkspaceError.message("本地服务没有返回有效资料。")
        }
        guard data.count <= 12 * 1024 * 1024 else {
            throw NativeWorkspaceError.message("本地资料超过读取上限。")
        }
        let decoded = try? JSONDecoder().decode(WorkspaceJSON.self, from: data)
        guard (200...299).contains(response.statusCode) else {
            throw NativeWorkspaceError.message(decoded?["error"].string ?? "本地资料暂不可用，请重试。")
        }
        guard let decoded = decoded else {
            throw NativeWorkspaceError.message("本地资料格式不正确，请重读资料。")
        }
        return decoded
    }

    private func validIdentifier(_ value: String) -> Bool {
        !value.isEmpty && value.count <= 128 && value.utf8.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0)
                || (97...122).contains($0) || $0 == 45 || $0 == 95 || $0 == 58
        }
    }

    private func safeRelativePath(_ value: String, allowLeadingSlash: Bool = false) -> Bool {
        var decoded = value
        for _ in 0..<4 {
            guard !decoded.contains("\\"), !containsControl(decoded),
                  allowLeadingSlash || !decoded.hasPrefix("/"),
                  !decoded.split(separator: "/", omittingEmptySubsequences: false)
                    .contains(where: { $0 == "." || $0 == ".." }) else { return false }
            let next = decoded.removingPercentEncoding ?? decoded
            if next == decoded { return true }
            decoded = next
        }
        return false
    }

    private func containsControl(_ value: String) -> Bool {
        value.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
    }

    private func readableError(_ error: Error) -> String {
        if let local = error as? NativeWorkspaceError { return local.localizedDescription }
        if error is CancellationError { return "读取已取消，可重新读取。" }
        return "无法连接本地资料，请确认工作区服务已启动后重试。"
    }
}
