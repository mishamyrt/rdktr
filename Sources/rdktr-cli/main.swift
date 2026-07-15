import Foundation
import Rdktr

func readInput() -> String? {
    let args = CommandLine.arguments
    if args.count > 1 {
        return try? String(contentsOfFile: args[1], encoding: .utf8)
    }
    let data = FileHandle.standardInput.readDataToEndOfFile()
    return String(data: data, encoding: .utf8)
}

guard let text = readInput(), !text.isEmpty else {
    FileHandle.standardError.write(Data("usage: rdktr-cli [file] (or pipe text to stdin)\n".utf8))
    exit(2)
}
guard let checker = TextChecker() else {
    FileHandle.standardError.write(Data("rdktr-cli: failed to load embedded rules\n".utf8))
    exit(1)
}

let issues = checker.check(text)
if issues.isEmpty {
    print("Чисто: стоп-слов не найдено.")
    exit(0)
}

// precompute line starts for line:column output
var lineStarts: [String.Index] = [text.startIndex]
var idx = text.startIndex
while idx < text.endIndex {
    if text[idx] == "\n" { lineStarts.append(text.index(after: idx)) }
    idx = text.index(after: idx)
}

func position(of index: String.Index) -> (line: Int, column: Int) {
    var line = lineStarts.count - 1
    while line > 0 && lineStarts[line] > index { line -= 1 }
    let column = text.distance(from: lineStarts[line], to: index) + 1
    return (line + 1, column)
}

for issue in issues {
    let (line, column) = position(of: issue.range.lowerBound)
    let fragment = text[issue.range].replacingOccurrences(of: "\n", with: "⏎")
    print("\(line):\(column)\t«\(fragment)» — \(issue.rule.title) [\(issue.rule.language)]")
    if !issue.rule.hint.isEmpty {
        print("\t\(issue.rule.hint)")
    }
}
print("\nВсего: \(issues.count)")
