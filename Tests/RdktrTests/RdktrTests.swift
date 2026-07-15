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
        XCTAssertEqual(titles("Это очень важно"), ["Усилители"])
        XCTAssertEqual(fragments("Это очень важно"), ["очень"])
    }

    func testExactPhrase() {
        let text = "Нельзя не отметить рост"
        XCTAssertEqual(titles(text), ["Канцеляризм"])
        XCTAssertEqual(fragments(text), ["Нельзя не отметить"])
    }

    func testPhraseSurvivesLineBreakAndSpaces() {
        XCTAssertEqual(titles("нельзя  не\nотметить"), ["Канцеляризм"])
    }

    func testPunctuationBreaksPhrase() {
        XCTAssertEqual(titles("нельзя, не отметить"), [])
    }

    func testCleanText() {
        XCTAssertEqual(titles("Кошка спит на подоконнике."), [])
    }

    // MARK: case and ё folding

    func testCaseInsensitive() {
        XCTAssertEqual(titles("ОЧЕНЬ"), ["Усилители"])
    }

    func testYoFolding() {
        // pattern "надёжный партнёр" must match with and without ё
        XCTAssertEqual(titles("надежный партнер"), ["Корпоративный штамп"])
        XCTAssertEqual(titles("надёжный партнёр"), ["Корпоративный штамп"])
    }

    // MARK: declensions (compile-time morphology)

    func testDeclensions() {
        XCTAssertEqual(titles("данного"), ["Канцеляризм"])
        XCTAssertEqual(titles("данным"), ["Канцеляризм"])
        XCTAssertEqual(titles("в данных обстоятельствах"), ["Канцеляризм"])
        XCTAssertEqual(titles("нет возможностей"), ["Рекламный штамп"]) // фичеризм.md title
        XCTAssertEqual(titles("существовали"), ["Слабый глагол"])
    }

    // MARK: prefix patterns

    func testPrefix() {
        XCTAssertEqual(titles("высококвалифицированными"), ["Необъективная оценка"])
        XCTAssertEqual(titles("высококвалифицированному специалисту приятно"),
                       ["Необъективная оценка", "Корпоративный штамп"])
    }

    // MARK: word boundaries

    func testNoSubwordMatches() {
        // "вы" is a rule word, "выше" must not match it
        XCTAssertEqual(titles("выше"), [])
        // "я" inside a word
        XCTAssertEqual(titles("яблоня"), [])
    }

    func testSingleLetterPronoun() {
        XCTAssertEqual(titles("я пошёл"), ["Личное местоимение"])
    }

    func testHyphenatedWordIsOneToken() {
        // "во-первых" must not trigger "вы"/"я" fragments and stays one token
        XCTAssertEqual(titles("во-первых"), [])
    }

    // MARK: overlaps, leftmost-longest

    func testLongestWins() {
        let text = "ни для кого не секрет"
        let issues = checker.check(text)
        XCTAssertEqual(issues.count, 1)
        XCTAssertEqual(String(text[issues[0].range]), "ни для кого не секрет")
    }

    func testShortAloneStillMatches() {
        XCTAssertEqual(titles("это не секрет"), ["Газетный штамп"])
    }

    func testSamePhraseInTwoRules() {
        // "сможете создать" belongs to газетный штамп and модальный глагол
        let found = Set(titles("вы сможете создать"))
        XCTAssertTrue(found.contains("Газетный штамп"))
        XCTAssertTrue(found.contains("Фраза с модальным глаголом"))
    }

    // MARK: comma rule (structural)

    func testTooManyCommas() {
        let text = "раз, два, три, четыре, пять, шесть, семь."
        XCTAssertTrue(titles(text).contains("Возможно, перебор с запятыми"))
    }

    func testFewCommasOK() {
        XCTAssertFalse(titles("раз, два и три.").contains("Возможно, перебор с запятыми"))
    }

    // MARK: ranges and metadata

    func testRangesPointAtOriginalText() {
        let text = "Слово ОЧЕНЬ выделено"
        let issues = checker.check(text)
        XCTAssertEqual(issues.count, 1)
        XCTAssertEqual(String(text[issues[0].range]), "ОЧЕНЬ")
    }

    func testRuleMetadata() {
        XCTAssertEqual(checker.rules.count, 18)
        let kanc = checker.rules.first { $0.title == "Канцеляризм" }
        XCTAssertNotNil(kanc)
        XCTAssertEqual(kanc?.weight, 100)
        XCTAssertFalse(kanc!.hint.isEmpty)
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
