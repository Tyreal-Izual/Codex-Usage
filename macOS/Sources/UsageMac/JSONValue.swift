import Foundation

/// Preserve the collectors' report contracts while upstream optional fields evolve.
enum JSONValue: Codable, Equatable, Sendable {
    case object([String: JSONValue]), array([JSONValue]), string(String)
    case number(Double), bool(Bool), null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    subscript(_ key: String) -> JSONValue {
        if case .object(let value) = self { return value[key] ?? .null }
        return .null
    }
    var items: [JSONValue] { if case .array(let value) = self { return value }; return [] }
    var object: [String: JSONValue] { if case .object(let value) = self { return value }; return [:] }
    var text: String { if case .string(let value) = self { return value }; return "" }
    var number: Double? { if case .number(let value) = self { return value }; return nil }
    var flag: Bool? { if case .bool(let value) = self { return value }; return nil }
    var display: String {
        switch self {
        case .string(let value): return value.isEmpty ? "—" : value
        case .number(let value): return value.formatted(.number.precision(.fractionLength(0...2)))
        case .bool(let value): return value ? "✓" : "—"
        case .array(let value): return value.map(\.display).joined(separator: ", ")
        default: return "—"
        }
    }
    var errorText: String {
        if !text.isEmpty { return text }
        for key in ["message", "error", "reason", "body_excerpt"] {
            let value = self[key]
            if value != .null { return value.errorText }
        }
        return ""
    }
}

struct BridgeReply: Decodable {
    let id: Int?
    let ok: Bool
    let result: JSONValue?
    let error: String?
}

enum BridgeError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let message) = self { return message }; return nil }
}

struct LimitWindows {
    let primary: JSONValue
    let weekly: JSONValue
    init(_ rate: JSONValue) {
        let first = rate["primary_window"], second = rate["secondary_window"]
        let hasFirst = first.object.values.contains { $0 != .null }
        let hasSecond = second.object.values.contains { $0 != .null }
        // Preserve the existing collector/UI contract for weekly-only accounts.
        primary = hasFirst && hasSecond ? first : .null
        weekly = hasSecond ? second : hasFirst ? first : .null
    }
}
