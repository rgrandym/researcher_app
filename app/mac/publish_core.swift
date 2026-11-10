// Publication core: validates a snapshot and writes it outside the workspace.
//
// Nothing here decides whether to write. The caller (publish_ui.swift) calls `apply` only
// after the author has reviewed the exact changes and authenticated. The functions refuse
// symlinks, hard links, special files, traversal and any change to a target since the snapshot.
// All file access goes through directory descriptors opened without following symlinks.

import Foundation
import CryptoKit

struct PublishOp: Codable {
    let path: String
    let action: String        // "write" | "delete"
    let expect: String        // "absent" | "sha256:<hex>"
    let sha256: String?
    let content: String?      // base64 of the UTF-8 text to write
}

struct PublishRequest: Codable {
    let version: Int
    let run: String
    let proposal: String
    let title: String
    let destination_root: String
    let operations: [PublishOp]
    let issued: Int
    let expires: Int
    let request_id: String
}

struct PublishError: Error, CustomStringConvertible {
    let description: String
    init(_ text: String) { description = text }
}

func sha256Hex(_ data: Data) -> String {
    "sha256:" + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

struct PlannedOp {
    let op: PublishOp
    let parts: [String]       // path components; the last is the file name
    let newData: Data?
    let oldData: Data?
}

enum PublishCore {
    static let maxOps = 32
    static let maxBytes = 2_000_000

    /// Static checks that need no file access.
    static func checkRequest(_ r: PublishRequest, now: Int) throws {
        guard r.version == 1 else { throw PublishError("Unknown request version.") }
        guard now <= r.expires else { throw PublishError("The request expired. Open Publish again.") }
        guard (1...maxOps).contains(r.operations.count) else { throw PublishError("Too many or no operations.") }
        guard r.destination_root.hasPrefix("/"), !r.destination_root.split(separator: "/").contains("..")
        else { throw PublishError("The destination must be an absolute path.") }
        var seen = Set<String>()
        for op in r.operations {
            let parts = try components(op.path)
            guard seen.insert(parts.joined(separator: "/").lowercased()).inserted
            else { throw PublishError("Duplicate target: \(op.path)") }
            guard op.action == "write" || op.action == "delete" else { throw PublishError("Unknown action.") }
            if op.action == "write" {
                guard let b64 = op.content, let data = Data(base64Encoded: b64), data.count <= maxBytes,
                    let text = String(data: data, encoding: .utf8), !text.contains("\0"),
                    op.sha256 == sha256Hex(data)
                else { throw PublishError("Content of \(op.path) does not match its hash.") }
            } else if op.expect == "absent" {
                throw PublishError("Cannot delete \(op.path): expected absent.")
            }
        }
    }

    static func components(_ path: String) throws -> [String] {
        let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !path.hasPrefix("/"), !parts.isEmpty else { throw PublishError("Bad path: \(path)") }
        for p in parts {
            if p.isEmpty || p == "." || p == ".." || p.utf8.count > 255
                || p.unicodeScalars.contains(where: { $0.value < 0x20 || $0.value == 0x7f || $0 == "\\" })
            { throw PublishError("Bad path: \(path)") }
        }
        return parts
    }

    /// The destination root must be deep enough not to be the home folder or a system folder.
    static func checkRoot(_ root: String) throws -> String {
        let real = URL(fileURLWithPath: root).resolvingSymlinksInPath().path
        let depth = real.split(separator: "/").count
        let home = FileManager.default.homeDirectoryForCurrentUser.resolvingSymlinksInPath().path
        guard depth >= 3, real != home, !real.hasPrefix("/System"), !real.hasPrefix("/usr"), !real.hasPrefix("/bin"),
            !real.hasPrefix("/Library"), !real.hasPrefix("/private/etc")
        else { throw PublishError("That destination is not allowed: \(real)") }
        return real
    }

    private static func openDir(_ parent: Int32, _ name: String) throws -> Int32 {
        let fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw PublishError("Cannot open folder \(name): \(String(cString: strerror(errno))).") }
        return fd
    }

    /// Opens the folder holding the target, one component at a time, never following a symlink.
    private static func parentFd(root: Int32, parts: [String]) throws -> Int32 {
        var current = dup(root)
        for name in parts.dropLast() {
            let next = try openDir(current, name)
            close(current)
            current = next
        }
        return current
    }

    /// The state of a target: nil when absent, its bytes when a plain file with one link.
    private static func read(dir: Int32, name: String) throws -> Data? {
        var info = stat()
        if fstatat(dir, name, &info, AT_SYMLINK_NOFOLLOW) != 0 {
            if errno == ENOENT { return nil }
            throw PublishError("Cannot inspect \(name).")
        }
        guard (info.st_mode & S_IFMT) == S_IFREG, info.st_nlink == 1, info.st_size <= maxBytes
        else { throw PublishError("\(name) is not a plain single-link file.") }
        let fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw PublishError("Cannot read \(name).") }
        defer { close(fd) }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let n = Foundation.read(fd, &buffer, buffer.count)
            if n < 0 { throw PublishError("Cannot read \(name).") }
            if n == 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }

    /// Reads every target and checks it still matches what the proposal expected. No mutation.
    static func plan(_ r: PublishRequest, root: String) throws -> [PlannedOp] {
        let rootFd = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard rootFd >= 0 else { throw PublishError("Cannot open the destination folder.") }
        defer { close(rootFd) }
        var planned: [PlannedOp] = []
        for op in r.operations {
            let parts = try components(op.path)
            let dir = try parentFd(root: rootFd, parts: parts)
            defer { close(dir) }
            let old = try read(dir: dir, name: parts.last!)
            switch (op.expect, old) {
            case ("absent", .none): break
            case ("absent", .some): throw PublishError("\(op.path) now exists; the proposal expected it absent.")
            case (_, .none): throw PublishError("\(op.path) is gone; the proposal expected a file.")
            case (let hash, .some(let data)):
                guard sha256Hex(data) == hash else { throw PublishError("\(op.path) changed since the proposal was made.") }
            }
            planned.append(PlannedOp(op: op, parts: parts, newData: op.content.flatMap { Data(base64Encoded: $0) }, oldData: old))
        }
        return planned
    }

    private static func writeTemp(dir: Int32, data: Data) throws -> String {
        let name = ".publish-\(UUID().uuidString)"
        let fd = openat(dir, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
        guard fd >= 0 else { throw PublishError("Cannot stage a file: \(String(cString: strerror(errno))).") }
        defer { close(fd) }
        let ok = data.withUnsafeBytes { raw -> Bool in
            var offset = 0
            while offset < raw.count {
                let n = Foundation.write(fd, raw.baseAddress! + offset, raw.count - offset)
                if n <= 0 { return false }
                offset += n
            }
            return true
        }
        guard ok, fsync(fd) == 0 else {
            unlinkat(dir, name, 0)
            throw PublishError("Cannot write a staged file.")
        }
        return name
    }

    /// Carries out a plan. Rechecks each target immediately before changing it. On a failure it
    /// restores what it already changed and reports whether the rollback succeeded.
    static func apply(_ planned: [PlannedOp], root: String) throws {
        let rootFd = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard rootFd >= 0 else { throw PublishError("Cannot open the destination folder.") }
        defer { close(rootFd) }
        // Stage all new content first: a failure here changes nothing at the destination.
        var staged: [Int: String] = [:]
        func cleanup() {
            for (index, name) in staged {
                if let dir = try? parentFd(root: rootFd, parts: planned[index].parts) {
                    unlinkat(dir, name, 0)
                    close(dir)
                }
            }
        }
        do {
            for (index, p) in planned.enumerated() where p.op.action == "write" {
                let dir = try parentFd(root: rootFd, parts: p.parts)
                defer { close(dir) }
                staged[index] = try writeTemp(dir: dir, data: p.newData!)
            }
        } catch {
            cleanup()
            throw error
        }
        var done: [Int] = []
        do {
            for (index, p) in planned.enumerated() {
                let dir = try parentFd(root: rootFd, parts: p.parts)
                defer { close(dir) }
                let name = p.parts.last!
                let now = try read(dir: dir, name: name)
                if let old = p.oldData {
                    guard let now, now == old else { throw PublishError("\(p.op.path) changed during publication.") }
                } else if now != nil {
                    throw PublishError("\(p.op.path) appeared during publication.")
                }
                if p.op.action == "delete" {
                    guard unlinkat(dir, name, 0) == 0 else { throw PublishError("Cannot delete \(p.op.path).") }
                } else if p.oldData == nil {
                    // Creation never replaces: renamex_np with RENAME_EXCL fails if the name exists.
                    guard renameatx_np(dir, staged[index]!, dir, name, UInt32(RENAME_EXCL)) == 0
                    else { throw PublishError("Cannot create \(p.op.path): \(String(cString: strerror(errno))).") }
                    staged[index] = nil
                } else {
                    guard renameat(dir, staged[index]!, dir, name) == 0
                    else { throw PublishError("Cannot replace \(p.op.path): \(String(cString: strerror(errno))).") }
                    staged[index] = nil
                }
                done.append(index)
            }
        } catch {
            cleanup()
            var failed: [String] = []
            for index in done.reversed() {
                let p = planned[index]
                do {
                    let dir = try parentFd(root: rootFd, parts: p.parts)
                    defer { close(dir) }
                    let name = p.parts.last!
                    if let old = p.oldData {
                        let temp = try writeTemp(dir: dir, data: old)
                        guard renameat(dir, temp, dir, name) == 0 else { throw PublishError("rename") }
                    } else {
                        unlinkat(dir, name, 0)
                    }
                } catch { failed.append(p.op.path) }
            }
            if failed.isEmpty { throw PublishError("\(error). Everything was rolled back.") }
            throw PublishError("\(error). Rollback failed for: \(failed.joined(separator: ", ")). Check these files.")
        }
    }
}
