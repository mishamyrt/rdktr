"""Rule linting: collect every problem instead of failing on the first one.

Runs the Compiler's own line pipeline (iter_line_sequences), so the linter
accepts exactly what the compiler accepts. On top of the syntax checks it
verifies front-matter descriptions and reports duplicate words and patterns —
including duplicates that only appear after '~' lexeme expansion (two lexemes
sharing inflected forms, or a plain word already covered by a lexeme
elsewhere).
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .compiler import COMMA_RULE_RE, Compiler
from .normalize import normalize
from .rule_file import (
    RuleError,
    expand_brackets,
    parse_rule_file,
    split_lint_ignore,
    split_tokens,
)

if TYPE_CHECKING:
    from pymorphy3 import MorphAnalyzer

# (display path, real 1-based line number, stripped source line)
type Occurrence = tuple[Path, int, str]

# red / yellow / magenta / cyan / cyan
KIND_COLORS = {
    "syntax": "31",
    "meta": "33",
    "dup": "35",
    "typo": "36",
    "warn": "36",
}

# '# lint-ignore: <tag>' tags the linter understands
KNOWN_IGNORE_TAGS = {"typo"}


@dataclass
class Diagnostic:
    path: Path
    line: int  # 0 = whole-file problem
    kind: str  # error: "syntax" | "meta" | "dup" | "typo"; non-fatal: "warn"
    message: str


def _group_order(group: tuple[tuple[Occurrence, ...], object]) -> tuple[str, int]:
    """Sort key for duplicate groups: location of the first occurrence."""
    (path, lineno, _), *_ = group[0]
    return (str(path), lineno)


class Linter:
    def __init__(
        self,
        lang: str,
        morph: "MorphAnalyzer | None" = None,
        root: Path | None = None,
    ) -> None:
        self.comp = Compiler(lang, morph)
        self.root = root  # paths are displayed relative to this directory
        self.diagnostics: list[Diagnostic] = []
        # concrete matchable word -> every pattern line that matches it
        self.word_occ: dict[str, list[Occurrence]] = {}
        # pattern line -> every single word it matches (for coverage advice)
        self.occ_forms: dict[Occurrence, set[str]] = {}
        self._shrink_cache: dict[Occurrence, str] = {}
        # expanded element sequence -> every pattern line that produces it
        self.pattern_occ: dict[tuple, list[Occurrence]] = {}
        self.comma_rule: Occurrence | None = None

    def _rel(self, path: Path) -> Path:
        if self.root is not None and path.is_relative_to(self.root):
            return path.relative_to(self.root)
        return path

    def diag(self, path: Path, line: int, kind: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(self._rel(path), line, kind, message))

    def lint_file(self, path: Path) -> None:
        try:
            meta, lines = parse_rule_file(path)
        except RuleError as e:
            self.diag(path, 0, "syntax", e.reason)
            return
        self._lint_meta(path, meta)
        for lineno, line in lines:
            self._lint_line(path, lineno, line)

    def _lint_meta(self, path: Path, meta: dict[str, str]) -> None:
        desc = meta.get("description", "")
        if not desc:
            self.diag(path, 0, "meta", "missing or empty description in front matter")
        elif not desc.endswith("."):
            self.diag(
                path, 0, "meta",
                f"description must end with a period: ...{desc[-40:]!r}",
            )
        try:
            int(meta.get("weight", "0"))
        except ValueError:
            self.diag(path, 0, "meta", "weight must be an integer")

    def _lint_line(self, path: Path, lineno: int, line: str) -> None:
        ctx = f"{path}:{lineno}"
        try:
            line, ignores = split_lint_ignore(line, ctx)
            for tag in sorted(ignores - KNOWN_IGNORE_TAGS):
                self.diag(
                    path, lineno, "warn",
                    f"unknown lint-ignore tag {tag!r}"
                    f" (known: {', '.join(sorted(KNOWN_IGNORE_TAGS))})",
                )
            if COMMA_RULE_RE.match(line):
                if self.comma_rule is not None:
                    p, n, _ = self.comma_rule
                    self.diag(
                        path, lineno, "syntax",
                        f"duplicate comma rule (already defined at {p}:{n})",
                    )
                else:
                    self.comma_rule = (self._rel(path), lineno, line)
                return
            occ: Occurrence = (self._rel(path), lineno, line)
            seen: set[tuple] = set()
            for seq in self.comp.iter_line_sequences(line, ctx):
                key = tuple(seq)
                if key in seen:
                    continue
                seen.add(key)
                el = seq[0]
                if len(seq) == 1 and el[0] in ("w", "l"):
                    forms = [el[1]] if el[0] == "w" else el[1]
                    for form in forms:
                        self.word_occ.setdefault(form, []).append(occ)
                        self.occ_forms.setdefault(occ, set()).add(form)
                else:
                    self.pattern_occ.setdefault(key, []).append(occ)
            if "typo" not in ignores:
                self._check_known(path, lineno, line, ctx)
        except RuleError as e:
            self.diag(path, lineno, "syntax", e.reason)

    def _check_known(self, path: Path, lineno: int, line: str, ctx: str) -> None:
        """'~слово' not in the morphological dictionary: the expansion is a
        paradigm guessed from the suffix, which almost always means a typo.
        Suppressed per line with '# lint-ignore: typo'."""
        if self.comp.morph is None or "~" not in line:
            return
        unknown: set[str] = set()
        for tok in split_tokens(line, ctx):
            for s in expand_brackets(tok, ctx):
                for w in s.split():
                    if "~" in w and not w.endswith("*"):
                        base = normalize(w.split("~", 1)[1])
                        if base and not self.comp.morph.word_is_known(base):
                            unknown.add(w)
        for w in sorted(unknown):
            base = w.split("~", 1)[1]
            self.diag(
                path, lineno, "typo",
                f"{base!r} is not in the morphological dictionary,"
                f" so {w!r} expands to a guessed paradigm — fix the typo"
                " or append '# lint-ignore: typo'",
            )

    # --- cross-file duplicate report ------------------------------------------

    @staticmethod
    def _fmt(occs: tuple[Occurrence, ...]) -> str:
        """Collapse adjacent identical occurrences (one line matching the same
        word through two overlapping '~' expansions) into 'loc ×N'."""
        collapsed: list[tuple[Occurrence, int]] = []
        for o in occs:
            if collapsed and collapsed[-1][0] == o:
                collapsed[-1] = (o, collapsed[-1][1] + 1)
            else:
                collapsed.append((o, 1))
        return ", ".join(
            f"{path}:{lineno} ({text!r})" + (f" ×{n}" if n > 1 else "")
            for (path, lineno, text), n in collapsed
        )

    @staticmethod
    def _fmt_forms(forms: list[str]) -> str:
        shown = ", ".join(map(repr, forms[:8]))
        extra = len(forms) - 8
        return shown + (f" (+{extra} more)" if extra > 0 else "")

    def _dup(self, occs: tuple[Occurrence, ...], message: str) -> None:
        path, lineno, _ = occs[0]
        self.diagnostics.append(Diagnostic(path, lineno, "dup", message))

    def _advice(self, occs: tuple[Occurrence, ...]) -> str:
        """Which of the overlapping pattern lines to keep: compare the full
        word sets each line matches (after '~' expansion)."""
        uniq = list(dict.fromkeys(occs))
        if len(uniq) < 2:
            # a line overlapping itself through its own alternatives:
            # suggest a shorter pattern with the same coverage
            return self._shrink_advice(uniq[0])
        sets = [self.occ_forms.get(o, set()) for o in uniq]
        if len(uniq) == 2 and sets[0] == sets[1]:
            return (
                f"; both match exactly the same {len(sets[0])} word(s)"
                " — keep either one"
            )
        best = max(range(len(uniq)), key=lambda i: len(sets[i]))
        others = [(o, s) for i, (o, s) in enumerate(zip(uniq, sets)) if i != best]
        if all(s <= sets[best] for _, s in others):
            drop = ", ".join(f"{p}:{n}" for (p, n, _), _ in others)
            return (
                f"; keep {uniq[best][2]!r} ({len(sets[best])} words)"
                f" — it fully covers the other"
                f"{'s' if len(others) > 1 else ''}; drop {drop}"
            )
        counts = ", ".join(f"{o[2]!r} {len(s)}" for o, s in zip(uniq, sets))
        return f"; neither covers the other — words per pattern: {counts}"

    def _shrink_advice(self, occ: Occurrence) -> str:
        """Greedy set cover over the line's bracket alternatives: the smallest
        subset of alternatives that still matches every word the line matches."""
        cached = self._shrink_cache.get(occ)
        if cached is not None:
            return cached
        self._shrink_cache[occ] = ""  # default until proven shrinkable
        path, lineno, line = occ
        ctx = f"{path}:{lineno}"
        try:
            toks = split_tokens(line, ctx)
            if len(toks) != 1:
                return ""
            variants = expand_brackets(toks[0], ctx)
            if len(variants) < 2 or any(
                not v or " " in v or v.endswith("*") for v in variants
            ):
                return ""
            sets: list[set[str]] = []
            for v in variants:
                forms: set[str] = set()
                for el in self.comp.word_elements(v, ctx):
                    if el[0] == "w":
                        forms.add(el[1])
                    elif el[0] == "l":
                        forms.update(el[1])
                    else:
                        return ""
                sets.append(forms)
        except RuleError:
            return ""
        universe = set().union(*sets)
        kept: list[int] = []
        covered: set[str] = set()
        while covered != universe:
            best = max(
                range(len(variants)), key=lambda i: (len(sets[i] - covered), -i)
            )
            if not sets[best] - covered:
                break
            kept.append(best)
            covered |= sets[best]
        if len(kept) >= len(variants):
            return ""
        suggestion = self._join_variants([variants[i] for i in sorted(kept)])
        advice = f"; same {len(universe)} words with just {suggestion!r}"
        self._shrink_cache[occ] = advice
        return advice

    @staticmethod
    def _join_variants(words: list[str]) -> str:
        """Kept alternatives -> pattern text: common prefix + [a|b] group."""
        if len(words) == 1:
            return words[0]
        prefix = words[0]
        for w in words[1:]:
            while not w.startswith(prefix):
                prefix = prefix[:-1]
        rests = [w[len(prefix):] for w in words]
        if any(not r for r in rests):
            rests = [r for r in rests if r]
            if prefix and rests:
                return f"{prefix}[{'|'.join(rests)}]?"
            return "[" + "|".join(words) + "]"
        if prefix:
            return f"{prefix}[{'|'.join(rests)}]"
        return "[" + "|".join(words) + "]"

    def report_duplicates(self) -> None:
        # group by the exact set of source lines so that two overlapping
        # lexemes produce one diagnostic listing the shared forms, not one
        # diagnostic per inflected form
        word_groups: dict[tuple[Occurrence, ...], list[str]] = {}
        for form, occs in sorted(self.word_occ.items()):
            if len(occs) > 1:
                word_groups.setdefault(tuple(occs), []).append(form)
        for occs, forms in sorted(word_groups.items(), key=_group_order):
            advice = self._advice(occs)
            if len(forms) == 1:
                self._dup(
                    occs,
                    f"duplicate word {forms[0]!r}:"
                    f" matched by {self._fmt(occs)}{advice}",
                )
            else:
                self._dup(
                    occs,
                    f"{len(forms)} duplicate words"
                    f" ({self._fmt_forms(forms)}):"
                    f" matched by {self._fmt(occs)}{advice}",
                )

        pattern_groups: dict[tuple[Occurrence, ...], int] = {}
        for occs in self.pattern_occ.values():
            if len(occs) > 1:
                key = tuple(occs)
                pattern_groups[key] = pattern_groups.get(key, 0) + 1
        for occs, n in sorted(pattern_groups.items(), key=_group_order):
            self._dup(
                occs,
                f"{n} duplicate pattern expansion(s): matched by {self._fmt(occs)}",
            )


def render(diags: list[Diagnostic], color: bool) -> str:
    """Diagnostics -> report grouped by file with aligned columns."""
    if color:
        def c(code: str, s: str) -> str:
            return f"\x1b[{code}m{s}\x1b[0m" if s else s
    else:
        def c(code: str, s: str) -> str:
            return s

    out: list[str] = []
    by_file: dict[str, list[Diagnostic]] = {}
    for d in diags:
        by_file.setdefault(str(d.path), []).append(d)
    kind_w = max((len(d.kind) for d in diags), default=0)
    for path in sorted(by_file):
        rows = sorted(by_file[path], key=lambda d: d.line)
        if out:
            out.append("")
        out.append(c("1;4", path))
        line_w = max((len(str(d.line)) for d in rows if d.line), default=0)
        for d in rows:
            ln = str(d.line) if d.line else ""
            out.append(
                f"  {c('2', ln.rjust(line_w))}  "
                f"{c(KIND_COLORS.get(d.kind, '31'), d.kind.ljust(kind_w))}"
                f"  {d.message}"
            )

    if out:
        out.append("")
    errors = [d for d in diags if d.kind != "warn"]
    warns = len(diags) - len(errors)
    if not diags:
        out.append(c("32", "✓ rules are clean"))
    elif not errors:
        out.append(c("1;33", f"⚠ {warns} warning(s)"))
    else:
        counts = Counter(d.kind for d in errors)
        breakdown = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        summary = f"✖ {len(errors)} problems ({breakdown})"
        if warns:
            summary += f", {warns} warning(s)"
        out.append(c("1;31", summary))
    return "\n".join(out)
