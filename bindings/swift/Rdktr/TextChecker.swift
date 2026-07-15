import CRdktr
import Foundation

/// A stop-word rule from the compiled rule set.
public struct Rule: Sendable, Hashable {
    public let id: Int
    /// Language of the rule set the rule belongs to, e.g. "ru" or "en".
    public let language: String
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
/// `TextChecker()` checks every embedded language and picks the language
/// per paragraph automatically (Cyrillic vs Latin script, with a fallback
/// to the document-dominant script). `TextChecker(language:)` pins one
/// language and skips detection.
///
/// The checker is immutable after creation and safe to share for reading,
/// but `check` allocates per call, so one instance per thread is cheapest.
public final class TextChecker {
    private enum Backend {
        case single(OpaquePointer)
        case multi(OpaquePointer)
    }

    private let backend: Backend
    private let externalBlob: UnsafeMutableRawBufferPointer?
    public let rules: [Rule]

    /// Languages embedded into the library at build time (e.g. ["en", "ru"]).
    public static var embeddedLanguages: [String] {
        (0..<rdktr_embedded_count()).compactMap {
            rdktr_embedded_lang($0).map { String(cString: $0) }
        }
    }

    /// All embedded languages, automatic per-paragraph detection.
    public convenience init?() {
        guard let multi = rdktr_multi_create_default() else { return nil }
        self.init(backend: .multi(multi), blob: nil)
    }

    /// One embedded language, no detection (e.g. `TextChecker(language: "ru")`).
    public convenience init?(language: String) {
        guard let engine = rdktr_create_embedded(language) else { return nil }
        self.init(backend: .single(engine), blob: nil)
    }

    /// A single custom rules blob (produced by `compile_rules.py --out-bin-dir`).
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
        self.init(backend: .single(engine), blob: buffer)
    }

    private init(backend: Backend, blob: UnsafeMutableRawBufferPointer?) {
        self.backend = backend
        self.externalBlob = blob
        switch backend {
        case .single(let engine):
            let lang = rdktr_lang(engine).map { String(cString: $0) } ?? ""
            self.rules = (0..<rdktr_rule_count(engine)).map { id in
                Rule(
                    id: Int(id),
                    language: lang,
                    title: rdktr_rule_title(engine, id).map { String(cString: $0) } ?? "",
                    hint: rdktr_rule_description(engine, id).map { String(cString: $0) } ?? "",
                    weight: Int(rdktr_rule_weight(engine, id))
                )
            }
        case .multi(let multi):
            self.rules = (0..<rdktr_multi_rule_count(multi)).map { id in
                Rule(
                    id: Int(id),
                    language: rdktr_multi_rule_lang(multi, id).map { String(cString: $0) } ?? "",
                    title: rdktr_multi_rule_title(multi, id).map { String(cString: $0) } ?? "",
                    hint: rdktr_multi_rule_description(multi, id).map { String(cString: $0) } ?? "",
                    weight: Int(rdktr_multi_rule_weight(multi, id))
                )
            }
        }
    }

    deinit {
        switch backend {
        case .single(let engine): rdktr_destroy(engine)
        case .multi(let multi): rdktr_multi_destroy(multi)
        }
        externalBlob?.deallocate()
    }

    private func rawCheck(_ base: UnsafePointer<CChar>, _ len: Int,
                          _ out: UnsafeMutablePointer<rdktr_match>?, _ cap: Int) -> Int {
        switch backend {
        case .single(let engine): return rdktr_check(engine, base, len, out, cap)
        case .multi(let multi): return rdktr_multi_check(multi, base, len, out, cap)
        }
    }

    /// Checks the text and returns all findings sorted by position.
    public func check(_ text: String) -> [Issue] {
        var utf8 = Array(text.utf8)
        guard !utf8.isEmpty else { return [] }

        let matches: [rdktr_match] = utf8.withUnsafeMutableBufferPointer { buf in
            let base = UnsafeRawPointer(buf.baseAddress!).assumingMemoryBound(to: CChar.self)
            let total = rawCheck(base, buf.count, nil, 0)
            guard total > 0 else { return [] }
            var out = [rdktr_match](repeating: rdktr_match(), count: total)
            let written = out.withUnsafeMutableBufferPointer {
                rawCheck(base, buf.count, $0.baseAddress, total)
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
