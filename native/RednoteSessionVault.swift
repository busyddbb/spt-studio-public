import Foundation
import WebKit
import Security
import LocalAuthentication

/// Rednote's session-only cookies stay in the local login Keychain. Persistent
/// cookies remain WebKit's responsibility. No cookie data is logged or exported.
@available(macOS 14.0, *)
final class RednoteSessionVault {
    static let shared = RednoteSessionVault()
    private let service: String
    private let defaults: UserDefaults
    private let allowsAuthenticationUI: Bool
    private let keychain = DispatchQueue(label: "local.spt.studio.rednote-session.keychain")
    private var profiles: [UUID: Profile] = [:]

    init(service: String = "local.spt.studio.rednote-session",
         defaults: UserDefaults = .standard, allowsAuthenticationUI: Bool = true) {
        self.service = service
        self.defaults = defaults
        self.allowsAuthenticationUI = allowsAuthenticationUI
    }

    func dataStore(profile: UUID) -> WKWebsiteDataStore { item(profile).store }

    func prepare(profile: UUID, onError: @escaping (String) -> Void,
                 completion: @escaping (Bool) -> Void) {
        let current = item(profile)
        current.errors.append(onError)
        if current.ready {
            if let error = current.lastError { onError(error) }
            completion(current.restoreSucceeded)
            return
        }
        current.waiting.append(completion)
        guard !current.restoring else { return }
        current.restoring = true
        let revision = current.revision
        keychain.async { [weak self, weak current] in
            guard let self = self, let current = current else { return }
            let result = self.read(current.id)
            DispatchQueue.main.async {
                guard current.revision == revision else { self.ready(current, succeeded: false); return }
                switch result {
                case .success(let data):
                    do {
                        let cookies = try self.restorableCookies(data, profile: current.id)
                        current.store.httpCookieStore.getAllCookies { existing in
                            guard current.revision == revision else { self.ready(current, succeeded: false); return }
                            let occupied = Set(existing.map(Self.cookieKey))
                            let restored = cookies.filter { !occupied.contains(Self.cookieKey($0)) }
                            let group = DispatchGroup()
                            for cookie in restored {
                                group.enter()
                                current.store.httpCookieStore.setCookie(cookie) { group.leave() }
                            }
                            group.notify(queue: .main) {
                                guard current.revision == revision else {
                                    let cleanup = DispatchGroup()
                                    for cookie in restored {
                                        cleanup.enter()
                                        current.store.httpCookieStore.delete(cookie) { cleanup.leave() }
                                    }
                                    cleanup.notify(queue: .main) { self.ready(current, succeeded: false) }
                                    return
                                }
                                self.ready(current, succeeded: true)
                            }
                        }
                    } catch {
                        self.invalidate(current.id)
                        self.ready(current, succeeded: false, error: error.localizedDescription)
                    }
                case .failure(let error):
                    // A refusal is not an empty Keychain. Invalidate restoration
                    // metadata before allowing a fresh website session to begin.
                    self.invalidate(current.id)
                    self.ready(current, succeeded: false, error: error.localizedDescription)
                }
            }
        }
    }

    func rejectSession(profile: UUID) {
        let current = item(profile)
        current.revision += 1
        current.captureEnabled = false
        invalidate(profile)
        keychain.async { [weak self, weak current] in
            guard let self = self, let current = current else { return }
            let result = self.remove(profile)
            DispatchQueue.main.async {
                if case .failure(let error) = result { current.errors.forEach { $0(error.localizedDescription) } }
            }
        }
    }

    /// Only the account pane calls this after checking rendered signed-in controls.
    func acceptSession(profile: UUID) {
        let current = item(profile)
        guard current.ready else { return }
        current.captureEnabled = true
        snapshot(current)
    }

    /// Called before app termination, while the website data stores still live.
    func flushAll(completion: @escaping (Bool) -> Void) {
        let active = profiles.values.filter { $0.ready }
        guard !active.isEmpty else { completion(true); return }
        let group = DispatchGroup()
        var succeeded = true
        for current in active {
            group.enter()
            snapshot(current) { ok in succeeded = succeeded && ok; group.leave() }
        }
        group.notify(queue: .main) { completion(succeeded) }
    }

    func flushForTermination(completion: @escaping (Bool) -> Void) {
        flushAll { [weak self] success in
            if success, let self = self {
                for current in self.profiles.values {
                    current.store.httpCookieStore.remove(current)
                    current.changed = nil
                }
            }
            completion(success)
        }
    }

    private func item(_ id: UUID) -> Profile {
        if let current = profiles[id] { return current }
        let current = Profile(id: id, store: WKWebsiteDataStore(forIdentifier: id))
        current.changed = { [weak self, weak current] in
            guard let self = self, let current = current, current.ready else { return }
            self.snapshot(current)
        }
        profiles[id] = current
        return current
    }

    private func ready(_ current: Profile, succeeded: Bool, error: String? = nil) {
        current.ready = true
        current.restoring = false
        current.restoreSucceeded = succeeded
        current.captureEnabled = succeeded
        current.lastError = error
        current.store.httpCookieStore.add(current)
        if let error = error { current.errors.forEach { $0(error) } }
        let callbacks = current.waiting
        current.waiting.removeAll()
        callbacks.forEach { $0(succeeded) }
    }

    private func snapshot(_ current: Profile, completion: ((Bool) -> Void)? = nil) {
        if let completion = completion { current.flushing.append(completion) }
        current.dirty = true
        guard !current.snapshotting else { return }
        takeSnapshot(current)
    }

    private func takeSnapshot(_ current: Profile) {
        current.snapshotting = true
        current.dirty = false
        current.store.httpCookieStore.getAllCookies { [weak self, weak current] cookies in
            guard let self = self, let current = current else { return }
            do {
                let properties = current.captureEnabled ? cookies.filter(Self.allowedCookie).map(Self.properties) : []
                let generation = UUID().uuidString
                // Write the non-sensitive generation first. If an old write or
                // deletion is denied, its old Keychain payload cannot resurrect
                // a logged-out session on the next launch.
                self.defaults.set(generation, forKey: self.marker(current.id))
                guard self.defaults.synchronize() else { throw self.failure("会话保存异常，请重新登录。") }
                let value: [String: Any] = ["version": 1, "generation": generation, "cookies": properties]
                let data = try PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0)
                self.keychain.async {
                    let result = properties.isEmpty ? self.remove(current.id) : self.write(data, profile: current.id)
                    DispatchQueue.main.async { self.snapshotFinished(current, result: result) }
                }
            } catch { self.snapshotFinished(current, result: .failure(error)) }
        }
    }

    private func snapshotFinished(_ current: Profile, result: Result<Void, Error>) {
        if case .failure(let error) = result {
            current.lastFlushSucceeded = false
            current.lastError = error.localizedDescription
            current.errors.forEach { $0(error.localizedDescription) }
        } else if current.captureEnabled {
            current.restoreSucceeded = true
            current.lastError = nil
        }
        if current.dirty { takeSnapshot(current); return }
        current.snapshotting = false
        let callbacks = current.flushing
        current.flushing.removeAll()
        let success = current.lastFlushSucceeded
        current.lastFlushSucceeded = true
        callbacks.forEach { $0(success) }
    }

    private static func cookieKey(_ cookie: HTTPCookie) -> String {
        cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
            + "\n" + cookie.path + "\n" + cookie.name
    }

    private func marker(_ id: UUID) -> String { "rednote.session-generation." + id.uuidString.lowercased() }
    private func invalidate(_ id: UUID) {
        defaults.set(UUID().uuidString, forKey: marker(id))
        defaults.synchronize()
    }

    private func restorableCookies(_ data: Data?, profile: UUID) throws -> [HTTPCookie] {
        guard let data = data else { return [] }
        guard let value = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any],
              value["version"] as? Int == 1, let generation = value["generation"] as? String,
              let saved = value["cookies"] as? [[String: Any]] else {
            throw failure("会话保存格式异常，请重新登录。")
        }
        guard defaults.string(forKey: marker(profile)) == generation else { return [] }
        return saved.compactMap { properties in
            let converted = Dictionary(uniqueKeysWithValues: properties.map { (HTTPCookiePropertyKey($0.key), $0.value) })
            guard let cookie = HTTPCookie(properties: converted), Self.allowedCookie(cookie) else { return nil }
            return cookie
        }
    }

    private static func allowedCookie(_ cookie: HTTPCookie) -> Bool {
        let domain = cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        let scoped = ["rednote.com", "xiaohongshu.com", "xhslink.com"].contains { domain == $0 || domain.hasSuffix("." + $0) }
        // Never rebase a Max-Age or extend an explicit expiry. These are owned
        // by WebKit's normal persistent-cookie implementation instead.
        return scoped && cookie.isSessionOnly && cookie.expiresDate == nil
            && cookie.properties?[.maximumAge] == nil
    }

    private static func properties(_ cookie: HTTPCookie) -> [String: Any] {
        var result: [String: Any] = [:]
        for (key, value) in cookie.properties ?? [:] {
            if let url = value as? URL { result[key.rawValue] = url.absoluteString }
            else if PropertyListSerialization.propertyList([value], isValidFor: .binary) { result[key.rawValue] = value }
        }
        return result
    }

    private func query(_ id: UUID) -> [String: Any] {
        var value: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: id.uuidString.lowercased(),
            kSecAttrSynchronizable as String: false]
        if !allowsAuthenticationUI {
            let context = LAContext()
            context.interactionNotAllowed = true
            value[kSecUseAuthenticationContext as String] = context
        }
        return value
    }

    private func read(_ id: UUID) -> Result<Data?, Error> {
        var value = query(id)
        value[kSecReturnData as String] = true
        value[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(value as CFDictionary, &result)
        if status == errSecItemNotFound { return .success(nil) }
        guard status == errSecSuccess, let data = result as? Data else { return .failure(keychainFailure(status)) }
        return .success(data)
    }

    private func write(_ data: Data, profile: UUID) -> Result<Void, Error> {
        let existing = query(profile)
        let status = SecItemUpdate(existing as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = existing
            item[kSecValueData as String] = data
            item[kSecAttrLabel as String] = "多媒体 · rednote 本机会话"
            let created = SecItemAdd(item as CFDictionary, nil)
            return created == errSecSuccess ? .success(()) : .failure(keychainFailure(created))
        }
        return status == errSecSuccess ? .success(()) : .failure(keychainFailure(status))
    }

    private func remove(_ id: UUID) -> Result<Void, Error> {
        let status = SecItemDelete(query(id) as CFDictionary)
        return [errSecSuccess, errSecItemNotFound].contains(status) ? .success(()) : .failure(keychainFailure(status))
    }

    private func keychainFailure(_ status: OSStatus) -> Error {
        failure("登录状态没能存进系统钥匙串（\(status)），下次可能要重新登录。")
    }
    private func failure(_ message: String) -> NSError {
        NSError(domain: "MediaDesk.RednoteSession", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private final class Profile: NSObject, WKHTTPCookieStoreObserver {
        let id: UUID
        let store: WKWebsiteDataStore
        var changed: (() -> Void)?
        var revision = 0
        var ready = false
        var restoreSucceeded = false
        var captureEnabled = true
        var lastError: String?
        var restoring = false
        var dirty = false
        var snapshotting = false
        var lastFlushSucceeded = true
        var errors: [(String) -> Void] = []
        var waiting: [(Bool) -> Void] = []
        var flushing: [(Bool) -> Void] = []
        init(id: UUID, store: WKWebsiteDataStore) { self.id = id; self.store = store }
        func cookiesDidChange(in cookieStore: WKHTTPCookieStore) {
            if Thread.isMainThread { changed?() }
            else { DispatchQueue.main.async { [weak self] in self?.changed?() } }
        }
    }
}
