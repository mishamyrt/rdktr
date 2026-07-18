import XCTest
@testable import Rdktr

final class RdktrTests: XCTestCase {
    var checker: TextChecker!

    override func setUp() {
        super.setUp()
        checker = TextChecker()
        XCTAssertNotNil(checker, "embedded rules must load")
    }

    private func titles(_ text: String) -> [String] {
        checker.check(text).map { $0.rule.title }
    }

    private func fragments(_ text: String) -> [String] {
        checker.check(text).map { String(text[$0.range]) }
    }

    // MARK: exact words and phrases

    func testExactWord() {
        XCTAssertEqual(titles("Это очень важно"), ["Усилители", "Необъективная оценка"])
        XCTAssertEqual(fragments("Это очень важно"), ["очень", "важно"])
    }

    func testExactPhrase() {
        let text = "Нельзя не отметить рост"
        XCTAssertEqual(titles(text), ["Канцеляризм"])
        XCTAssertEqual(fragments(text), ["Нельзя не отметить"])
    }

    func testEmptyAndDegenerateInput() {
        XCTAssertEqual(checker.check("").count, 0)
        XCTAssertEqual(checker.check(" \n\t ").count, 0)
        XCTAssertEqual(checker.check("…—«»").count, 0)
    }

    func testInvalidBlobRejected() {
        XCTAssertNil(TextChecker(blob: Data()))
        XCTAssertNil(TextChecker(blob: Data("garbage-not-a-blob".utf8)))
    }

    // MARK: throughput

    func testThroughputOnMegabyteOfText() {
        let paragraph = """
        Наша компания является лидером рынка и осуществляет деятельность \
        в сфере высоких технологий. Данный продукт позволяет получить \
        качественный результат. Ни для кого не секрет, что мы предлагаем \
        широкий спектр услуг и индивидуальный подход. Кошка спит на окне, \
        а собака гуляет во дворе около дома у реки.
        """
        var text = ""
        while text.utf8.count < 1_000_000 { text += paragraph + "\n" }
        let bytes = text.utf8.count

        let start = Date()
        let issues = checker.check(text)
        let elapsed = Date().timeIntervalSince(start)

        XCTAssertGreaterThan(issues.count, 1000)
        let mbps = Double(bytes) / 1_048_576 / elapsed
        print("rdktr throughput: \(String(format: "%.1f", mbps)) MiB/s, \(issues.count) matches in \(String(format: "%.1f", elapsed * 1000)) ms")
        XCTAssertGreaterThan(mbps, 5, "engine should stay well above 5 MiB/s")
    }
}
