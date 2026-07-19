"""Rule file parsing: front matter metadata + pattern line tokenization."""

import re
from pathlib import Path


class RuleError(Exception):
    """A problem in a rule file, tied to a location.

    `ctx` is "path" or "path:line"; `reason` is the message without the
    location prefix. str() gives the full "ctx: reason" form for CLI use.
    """

    def __init__(self, ctx: str, reason: str) -> None:
        super().__init__(f"{ctx}: {reason}")
        self.ctx = ctx
        self.reason = reason


def parse_rule_file(path: Path) -> tuple[dict[str, str], list[tuple[int, str]]]:
    """Front matter metadata + non-empty body lines with their real
    1-based line numbers."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise RuleError(str(path), "missing front matter")
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        m = re.match(r"^(\w+):\s*(.*)$", lines[i])
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ""):  # folded / literal block scalar
                i += 1
                block = []
                while i < len(lines) and (lines[i].startswith((" ", "\t")) or lines[i] == ""):
                    if lines[i].strip():
                        block.append(lines[i].strip())
                    i += 1
                meta[key] = " ".join(block)
                continue
            meta[key] = val.strip("\"'")
        i += 1
    if i >= len(lines):
        raise RuleError(str(path), "unterminated front matter")
    patterns = [
        (n, ln.strip())
        for n, ln in enumerate(lines[i + 1 :], start=i + 2)
        if ln.strip()
    ]
    return meta, patterns


LINT_IGNORE_RE = re.compile(r"\s*#\s*lint-ignore:\s*([\w, -]+)$")
UNESCAPED_HASH_RE = re.compile(r"(?<!\\)#")


def split_lint_ignore(line: str, ctx: str) -> tuple[str, frozenset[str]]:
    """'# lint-ignore: <tag>[, <tag>...]' at the end of a pattern line
    suppresses the named linter checks for that line (e.g. 'typo' keeps the
    dictionary check quiet for a deliberately unusual word). The marker is
    not part of the pattern and is stripped before compilation.

    Any other unescaped '#' is a malformed marker, not a pattern character:
    without this a forgotten tag would surface as a baffling word-character
    error. A literal '#' must be escaped as '\\#'."""
    m = LINT_IGNORE_RE.search(line)
    tags: frozenset[str] = frozenset()
    if m:
        tags = frozenset(t.strip() for t in m.group(1).split(",") if t.strip())
        line = line[: m.start()].rstrip()
    if UNESCAPED_HASH_RE.search(line):
        raise RuleError(
            ctx,
            "malformed lint-ignore marker; expected '# lint-ignore: <tag>'"
            " at the end of the line (escape a literal '#' as '\\#')",
        )
    return line, tags


def split_tokens(line: str, ctx: str) -> list[str]:
    """Whitespace split that keeps [...] groups (which may contain spaces)
    together with their token."""
    toks: list[str] = []
    cur, depth = "", 0
    esc = False
    for ch in line:
        if esc:  # a backslash-escaped char is literal, e.g. \[ or \(
            esc = False
            cur += ch
        elif ch == "\\":
            esc = True
            cur += ch
        elif ch == "[":
            depth += 1
            cur += ch
        elif ch == "]":
            if depth == 0:
                raise RuleError(ctx, f"unbalanced ']' in {line!r}")
            depth -= 1
            cur += ch
        elif ch.isspace() and depth == 0:
            if cur:
                toks.append(cur)
                cur = ""
        else:
            cur += ch
    if esc:
        raise RuleError(ctx, f"dangling '\\' at end of line: {line!r}")
    if depth:
        raise RuleError(ctx, f"unbalanced '[' in {line!r}")
    if cur:
        toks.append(cur)
    return toks


def expand_brackets(tok: str, ctx: str) -> list[str]:
    """Expand [a|b] groups into plain strings. '?' right after ']' adds an
    empty variant. Returns a list of strings (a variant may contain spaces
    or be empty)."""
    i = tok.find("[")
    if i < 0:
        return [tok]
    j = tok.find("]", i)
    if j < 0:
        raise RuleError(ctx, f"unbalanced '[' in {tok!r}")
    if tok.find("[", i + 1) != -1 and tok.find("[", i + 1) < j:
        raise RuleError(ctx, f"nested '[' is not supported: {tok!r}")
    variants = tok[i + 1 : j].split("|")
    rest = tok[j + 1 :]
    if rest.startswith("?"):
        variants.append("")
        rest = rest[1:]
    out: list[str] = []
    for tail in expand_brackets(rest, ctx):
        for v in variants:
            out.append(tok[:i] + v + tail)
    return out
