"""Rule file parsing: front matter metadata + pattern line tokenization."""

import re
from pathlib import Path


def parse_rule_file(path: Path) -> tuple[dict[str, str], list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise SystemExit(f"{path}: missing front matter")
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
        raise SystemExit(f"{path}: unterminated front matter")
    body = [ln.strip() for ln in lines[i + 1 :]]
    patterns = [ln for ln in body if ln]
    return meta, patterns


def split_tokens(line: str, ctx: str) -> list[str]:
    """Whitespace split that keeps [...] groups (which may contain spaces)
    together with their token."""
    toks: list[str] = []
    cur, depth = "", 0
    for ch in line:
        if ch == "[":
            depth += 1
            cur += ch
        elif ch == "]":
            if depth == 0:
                raise SystemExit(f"{ctx}: unbalanced ']' in {line!r}")
            depth -= 1
            cur += ch
        elif ch.isspace() and depth == 0:
            if cur:
                toks.append(cur)
                cur = ""
        else:
            cur += ch
    if depth:
        raise SystemExit(f"{ctx}: unbalanced '[' in {line!r}")
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
        raise SystemExit(f"{ctx}: unbalanced '[' in {tok!r}")
    if tok.find("[", i + 1) != -1 and tok.find("[", i + 1) < j:
        raise SystemExit(f"{ctx}: nested '[' is not supported: {tok!r}")
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
