"""Rule file formatting: lowercase patterns and sort them alphabetically.

The sort key ignores syntax markers (`~ * ! _ [ ] | ? ( ) \\ #` and the
`# lint-ignore` marker), so `~сомнительное ~удовольствие` sorts as
"сомнительное удовольствие". Front matter is preserved verbatim.
"""

from pathlib import Path

from .normalize import is_word_char
from .rule_file import LINT_IGNORE_RE, RuleError


def sort_key(line: str) -> str:
    """A pattern's alphabetical sort key: syntax markers dropped, letters
    lowercased, runs of whitespace collapsed to a single space."""
    line = LINT_IGNORE_RE.sub("", line).lower()
    out = []
    for ch in line:
        if ch.isspace():
            out.append(" ")
        elif is_word_char(ch):
            out.append(ch)
    return " ".join("".join(out).split())


def lower_pattern(line: str) -> str:
    """Lowercase the pattern, leaving any trailing `# lint-ignore` marker
    (whose tags are case-sensitive linter check names) untouched."""
    m = LINT_IGNORE_RE.search(line)
    if not m:
        return line.lower()
    return f"{line[: m.start()].rstrip().lower()} {line[m.start():].strip()}"


def format_text(text: str, ctx: str) -> str:
    """Return `text` with body patterns lowercased and sorted. Front matter
    (everything up to and including the closing `---`) is kept verbatim."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise RuleError(ctx, "missing front matter")
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    if i >= len(lines):
        raise RuleError(ctx, "unterminated front matter")

    front = lines[: i + 1]
    body = [lower_pattern(ln.strip()) for ln in lines[i + 1 :] if ln.strip()]
    body.sort(key=lambda ln: (sort_key(ln), ln))
    return "\n".join(front) + "\n\n" + "\n".join(body) + "\n"


def format_file(path: Path) -> bool:
    """Rewrite `path` in place if formatting changes it. Returns whether the
    file was already formatted (True = no change needed)."""
    original = path.read_text(encoding="utf-8")
    formatted = format_text(original, str(path))
    if formatted != original:
        path.write_text(formatted, encoding="utf-8")
        return False
    return True
