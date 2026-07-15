import CRdktr
import Foundation

/// A stop-word rule from the compiled rule set.
public struct Rule: Sendable, Hashable {
    public let id: Int
    public let title: String
    public let hint: String
    public let weight: Int
}

/// A single finding: a range of the checked string and the rule it violates.
public struct Issue: Sendable {
    public let range: Range<String.Index>
    public let rule: Rule
}

/// Text-cleanliness checker backed by the C engine.
///
/// The engine is immutable after creation and safe to share for reading,
/// but `check` allocates per call, so one instance per thread is cheapest.
public final class TextChecker {
    private let engine: OpaquePointer
    private let externalBlob: UnsafeMutableRawBufferPointer?
    public let rules: [Rule]

    /// Creates a checker with the rule set embedded at build time.
    public convenience init?() {
        guard let engine = rdktr_create_default() else { return nil }
        self.init(engine: engine, blob: nil)
    }

    /// Creates a checker from an externally compiled rules blob
    /// (produced by `Scripts/compile_rules.py --out-bin`).
    public convenience init?(blob: Data) {
        let buffer = UnsafeMutableRawBufferPointer.allocate(
            byteCount: blob.count,
            alignment: 4
        )
        blob.copyBytes(to: buffer)
        guard let engine = rdktr_create(buffer.baseAddress, buffer.count) else {
            buffer.deallocate()
            return nil
        }
        self.init(engine: engine, blob: buffer)
    }

    private init(engine: OpaquePointer, blob: UnsafeMutableRawBufferPointer?) {
        self.engine = engine
        self.externalBlob = blob
        self.rules = (0..<rdktr_rule_count(engine)).map { id in
            Rule(
                id: Int(id),
                title: rdktr_rule_title(engine, id).map { String(cString: $0) } ?? "",
                hint: rdktr_rule_description(engine, id).map { String(cString: $0) } ?? "",
                weight: Int(rdktr_rule_weight(engine, id))
            )
        }
    }

    deinit {
        rdktr_destroy(engine)
        externalBlob?.deallocate()
    }

    /// Checks the text and returns all findings sorted by position.
    public func check(_ text: String) -> [Issue] {
        var utf8 = Array(text.utf8)
        guard !utf8.isEmpty else { return [] }

        let matches: [rdktr_match] = utf8.withUnsafeMutableBufferPointer { buf in
            let base = UnsafeRawPointer(buf.baseAddress!).assumingMemoryBound(to: CChar.self)
            let total = rdktr_check(engine, base, buf.count, nil, 0)
            guard total > 0 else { return [] }
            var out = [rdktr_match](repeating: rdktr_match(), count: total)
            let written = out.withUnsafeMutableBufferPointer {
                rdktr_check(engine, base, buf.count, $0.baseAddress, total)
            }
            precondition(written == total, "engine returned inconsistent match count")
            return out
        }

        let u8 = text.utf8
        return matches.compactMap { m in
            guard
                let start = u8.index(u8.startIndex, offsetBy: Int(m.start), limitedBy: u8.endIndex),
                let end = u8.index(u8.startIndex, offsetBy: Int(m.end), limitedBy: u8.endIndex),
                start <= end,
                Int(m.rule_id) < rules.count
            else { return nil }
            return Issue(range: start..<end, rule: rules[Int(m.rule_id)])
        }
    }
}
