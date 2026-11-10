struct OccurrenceID: Hashable {
    let key: String
    let occurrence: Int
}

struct IdentifiedValue<Value>: Identifiable {
    let id: OccurrenceID
    let value: Value
}

/// Preserve upstream order while giving duplicate keys distinct, repeatable identities.
func identifiedValues<Value>(_ values: [Value], key: (Value) -> String) -> [IdentifiedValue<Value>] {
    var occurrences: [String: Int] = [:]
    return values.map { value in
        let identity = key(value)
        let occurrence = occurrences[identity, default: 0]
        occurrences[identity] = occurrence + 1
        return IdentifiedValue(id: OccurrenceID(key: identity, occurrence: occurrence), value: value)
    }
}
