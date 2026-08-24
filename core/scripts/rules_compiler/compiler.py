"""Pattern compilation: rule files -> element sequences (patterns)."""

import re
import sys
from collections.abc import Iterator
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from .constants import (
    ELEM_ANY,
    ELEM_GAP,
    ELEM_LEXEME,
    ELEM_PREFIX,
    ELEM_PUNCT,
    ELEM_PUNCT_RUN,
    ELEM_WORD,
    MAX_ANY_SPAN,
    MAX_COMBOS,
    MAX_GAP,
    MAX_PUNCT_RUN,
    NONE,
)
from .normalize import is_word_char, normalize, word_variants
from .rule_file import (
    RuleError,
    expand_brackets,
    parse_rule_file,
    split_lint_ignore,
    split_tokens,
)

if TYPE_CHECKING:
    from pymorphy3 import MorphAnalyzer

COMMA_RULE_RE = re.compile(r"^_(\s*,\s*_)+$")
STANDALONE_STAR_RE = re.compile(r"(^|\s)\*(\s|$|,)")
GAP_RE = re.compile(r"^_(?:\((\d+)(?:-(\d+))?\))?$")
# A standalone punctuation token: one bare char (that is not a syntax
# metacharacter) or any backslash-escaped char, plus an optional repeat
# count in the gap style: !(2), !(2-5), !(2+). A bare '?' is only a
# metacharacter right after ']' (inside a token); standalone it is a
# literal question mark.
PUNCT_TOKEN_RE = re.compile(
    r"^(?:\\(?P<esc>[^\w\s])|(?P<bare>[^\w\s~*\[\]|_()\\]))"
    r"(?:\((?P<lo>\d+)(?:-(?P<hi>\d+))?(?P<plus>\+)?\))?$"
)

# ("w", form) | ("p", stem) | ("l", forms) | ("g", lo, hi) | ("c", codepoint)
# | ("C", codepoint, lo, hi) punctuation run, hi == 0 means unbounded
# | ("a", lo, hi) wide gap `__`: words and punctuation both count;
# "l" carries a sorted tuple of >= 2 inflected forms matched as one element.
type Element = (
    tuple[str, str]
    | tuple[str, tuple[str, ...]]
    | tuple[str, int, int]
    | tuple[str, int]
    | tuple[str, int, int, int]
)
# One pattern-line token expanded: alternatives, each a sequence of elements
# (empty for an optional word that is absent).
type Slot = list[list[Element]]
# Serialized element: (kind, payload, extra) — see rdktr_internal.h.
type PatternKey = tuple[tuple[int, int, int], ...]


class Rule(TypedDict):
    title: str
    description: str
    weight: int


class Compiler:
    def __init__(self, lang: str, morph: "MorphAnalyzer | None" = None) -> None:
        if not (1 <= len(lang) <= 3) or not lang.isascii() or not lang.isalpha():
            raise SystemExit(f"language code must be 1-3 ASCII letters, got {lang!r}")
        self.lang = lang.lower()
        self.morph = morph
        self.rules: list[Rule] = []
        self.word_ids: dict[str, int] = {}  # word -> id
        self.prefix_ids: dict[str, int] = {}  # stem -> id
        self.patterns: list[set[int]] = []  # pattern_id -> set(rule_ids)
        self.pattern_keys: list[PatternKey] = []  # pattern_id -> tuple of elements
        self.pattern_by_key: dict[PatternKey, int] = {}
        self.lexeme_ids: dict[tuple[int, ...], int] = {}  # word-id set -> id
        self.lexeme_sets: list[tuple[int, ...]] = []  # lexeme_id -> word ids
        self.comma_rule_id = NONE
        self.comma_threshold = 0
        self.comma_rule_ctx = ""  # where the comma rule was defined
        self.form_count = 0
        self.stats: dict[str, int] = {}

    def word_id(self, word: str) -> int:
        wid = self.word_ids.get(word)
        if wid is None:
            wid = len(self.word_ids)
            self.word_ids[word] = wid
        return wid

    def prefix_id(self, stem: str) -> int:
        pid = self.prefix_ids.get(stem)
        if pid is None:
            pid = len(self.prefix_ids)
            self.prefix_ids[stem] = pid
        return pid

    def lexeme_id(self, wids: list[int]) -> int:
        key = tuple(sorted(set(wids)))
        lid = self.lexeme_ids.get(key)
        if lid is None:
            lid = len(self.lexeme_sets)
            self.lexeme_ids[key] = lid
            self.lexeme_sets.append(key)
        return lid

    def _pattern(self, key: PatternKey) -> int:
        pid = self.pattern_by_key.get(key)
        if pid is None:
            pid = len(self.patterns)
            self.pattern_by_key[key] = pid
            self.patterns.append(set())
            self.pattern_keys.append(key)
        return pid

    def _validate_word(self, word: str, ctx: str) -> None:
        if not word:
            raise RuleError(ctx, "empty word in pattern")
        for ch in word:
            if not is_word_char(ch):
                raise RuleError(ctx, f"character {ch!r} cannot appear in a word")
        if word[0] in "-'" or word[-1] in "-'":
            raise RuleError(ctx, f"word cannot start/end with a connector: {word!r}")

    def expand_lexeme(self, word: str, ctx: str) -> list[str]:
        if self.morph is None:
            raise RuleError(
                ctx,
                "'~' morphology expansion is only available for Russian"
                " rules (pymorphy3); use a prefix pattern (основ*) instead",
            )
        parses = self.morph.parse(word)
        if not parses:
            raise RuleError(ctx, f"pymorphy3 cannot parse {word!r}")
        forms = {normalize(f.word) for f in parses[0].lexeme}
        forms.add(normalize(word))
        return sorted(forms)

    # --- pattern line -> element sequences ------------------------------------

    def word_elements(self, word: str, ctx: str) -> list[Element]:
        """One plain word (no brackets, no gaps) -> list of single elements.

        '~' may appear mid-word (црм-~система): the head stays literal and
        the tail after '~' is expanded, so every inflected form keeps the
        head glued on (црм-система, црм-системы, ...)."""
        tilde = word.find("~")
        if tilde >= 0:
            head, tail = word[:tilde], word[tilde + 1 :]
            if "~" in tail:
                raise RuleError(ctx, f"at most one '~' per word: {word!r}")
            if not tail:
                raise RuleError(ctx, f"'~' must be followed by a word: {word!r}")
            if tail.endswith("*"):
                # the prefix already covers every inflected form
                print(
                    f"note: {ctx}: {word!r} compiled as prefix"
                    f" {head + tail[:-1]!r}",
                    file=sys.stderr,
                )
                word = head + tail[:-1] + "*"
            else:
                head = normalize(head)
                forms = [
                    head + f for f in self.expand_lexeme(normalize(tail), ctx)
                ]
                for f in forms:
                    self._validate_word(f, ctx)
                self.form_count += len(forms)
                if len(forms) == 1:
                    return [("w", forms[0])]
                return [("l", tuple(forms))]
        if word.endswith("*"):
            stem = normalize(word[:-1])
            if "*" in stem:
                raise RuleError(
                    ctx,
                    "'*' is only valid at the end of a word;"
                    f" for an optional apostrophe use don['|’]?t: {word!r}",
                )
            self._validate_word(stem, ctx)
            return [("p", v) for v in word_variants(stem)]
        if "*" in word:
            raise RuleError(
                ctx,
                "'*' is only valid at the end of a word;"
                f" for an optional apostrophe use don['|’]?t: {word!r}",
            )
        w = normalize(word)
        self._validate_word(w, ctx)
        return [("w", v) for v in word_variants(w)]

    def punct_slot(self, m: "re.Match[str]", ctx: str) -> Slot:
        """Matched PUNCT_TOKEN_RE -> a single punctuation element."""
        ch = m.group("esc") or m.group("bare")
        cp = ord(ch)
        if m.group("lo") is None:
            return [[("c", cp)]]
        lo = int(m.group("lo"))
        if m.group("plus"):
            hi = 0  # unbounded
        elif m.group("hi") is not None:
            hi = int(m.group("hi"))
        else:
            hi = lo
        if lo < 1 or lo > MAX_PUNCT_RUN or hi > MAX_PUNCT_RUN or (hi and hi < lo):
            raise RuleError(
                ctx,
                f"bad punctuation count in {m.group(0)!r}"
                f" (need 1 <= min <= max <= {MAX_PUNCT_RUN})",
            )
        if (lo, hi) == (1, 1):
            return [[("c", cp)]]
        return [[("C", cp, lo, hi)]]

    def token_slot(self, tok: str, ctx: str) -> Slot:
        """Raw token -> list of alternatives; each alternative is a list of
        elements (empty for an optional word that is absent)."""
        m = GAP_RE.match(tok)
        if m:
            if m.group(1) is None:
                lo = hi = 1
            else:
                lo = int(m.group(1))
                hi = int(m.group(2)) if m.group(2) is not None else lo
            if hi < 1 or lo > hi or hi > MAX_GAP:
                raise RuleError(
                    ctx,
                    f"bad gap {tok!r} (need 0 <= min <= max,"
                    f" 1 <= max <= {MAX_GAP})",
                )
            return [[("g", lo, hi)]]
        if tok == "__":
            return [[("a", 1, MAX_ANY_SPAN)]]
        if tok.startswith("_"):
            raise RuleError(ctx, f"bad gap syntax {tok!r}; use _, _(2) or _(0-3)")
        if "\\" in tok:
            raise RuleError(
                ctx,
                "'\\' only escapes a standalone punctuation"
                f" character, e.g. \\( or \\): {tok!r}",
            )
        alts: Slot = []
        for s in expand_brackets(tok, ctx):
            if "?" in s:
                raise RuleError(
                    ctx,
                    "'?' is only valid right after ']' or standalone"
                    f" as a literal question mark: {tok!r}",
                )
            if s == "":
                alts.append([])
                continue
            per_word = [self.word_elements(w, ctx) for w in s.split()]
            for combo in product(*per_word):
                alts.append(list(combo))
        return alts

    def line_slots(self, line: str, ctx: str) -> list[Slot]:
        """Pattern line -> list of slots; each slot is a list of alternatives."""
        slots: list[Slot] = []
        punct_slot: Slot = [[("c", ord(","))]]
        for tok in split_tokens(line, ctx):
            m = PUNCT_TOKEN_RE.match(tok)
            if m:  # standalone punctuation, possibly with a repeat count
                slots.append(self.punct_slot(m, ctx))
                continue
            trailing = 0
            while tok.endswith(","):
                tok = tok[:-1]
                trailing += 1
            while tok.startswith(","):
                slots.append(punct_slot)
                tok = tok[1:]
            if tok:
                slots.append(self.token_slot(tok, ctx))
            slots.extend([punct_slot] * trailing)
        return slots

    def _check_sequence(self, seq: list[Element], ctx: str, line: str) -> None:
        kinds = [el[0] for el in seq]
        if kinds[0] not in ("w", "p", "l", "c", "C"):
            raise RuleError(ctx, f"pattern cannot start with a gap: {line!r}")
        if kinds[-1] in ("g", "a"):
            raise RuleError(ctx, f"pattern cannot end with a gap: {line!r}")
        for a, b in zip(kinds, kinds[1:]):
            if a in ("g", "a") and b in ("g", "a"):
                raise RuleError(
                    ctx, f"adjacent gaps; merge them into one _(n-m): {line!r}"
                )
            if a in ("g", "a") and b == "C":
                raise RuleError(
                    ctx,
                    "a punctuation repeat cannot follow a gap;"
                    f" anchor it with a word or a single sign first: {line!r}",
                )

    def iter_line_sequences(
        self, line: str, ctx: str
    ) -> Iterator[list[Element]]:
        """One pattern line (lint-ignore marker already stripped, comma rule
        already handled) -> every expanded, validated element sequence.

        This is the single line-processing pipeline shared by compilation
        and linting, so both always accept exactly the same syntax."""
        if "*" in line and STANDALONE_STAR_RE.search(line):
            raise RuleError(
                ctx,
                "standalone '*' is gone; use '_' for any word"
                f" (comma rule: '_, _, ...'): {line!r}",
            )
        slots = self.line_slots(line, ctx)
        if not slots:
            raise RuleError(ctx, "empty pattern")
        combos = 1
        for slot in slots:
            combos *= len(slot)
        if combos > MAX_COMBOS:
            raise RuleError(
                ctx, f"too many form combinations ({combos}) in {line!r}"
            )
        for combo in product(*slots):
            seq = [el for alt in combo for el in alt]
            if not seq:
                raise RuleError(
                    ctx, f"pattern expands to an empty sequence: {line!r}"
                )
            self._check_sequence(seq, ctx, line)
            yield seq

    def add_rule_file(self, path: Path) -> None:
        meta, lines = parse_rule_file(path)
        title = meta.get("title", path.stem)
        description = meta.get("description", "")
        try:
            weight = int(meta.get("weight", "0"))
        except ValueError:
            raise RuleError(str(path), "weight must be an integer") from None
        rule_id = len(self.rules)
        self.rules.append(
            {"title": title, "description": description, "weight": weight}
        )

        for n, raw in lines:
            ctx = f"{path}:{n}"
            line, _ = split_lint_ignore(raw, ctx)
            if COMMA_RULE_RE.match(line):
                # the blob holds exactly one comma rule, so a second one
                # would silently replace the first
                if self.comma_rule_id != NONE:
                    raise RuleError(
                        ctx,
                        "duplicate comma rule (already defined at"
                        f" {self.comma_rule_ctx})",
                    )
                self.comma_rule_id = rule_id
                self.comma_threshold = line.count(",")
                self.comma_rule_ctx = ctx
                continue
            for seq in self.iter_line_sequences(line, ctx):
                key: list[tuple[int, int, int]] = []
                for el in seq:
                    if el[0] == "w":
                        key.append((ELEM_WORD, self.word_id(el[1]), 0))
                    elif el[0] == "p":
                        key.append((ELEM_PREFIX, self.prefix_id(el[1]), 0))
                    elif el[0] == "l":
                        wids = [self.word_id(f) for f in el[1]]
                        key.append((ELEM_LEXEME, self.lexeme_id(wids), 0))
                    elif el[0] == "g":
                        key.append((ELEM_GAP, el[1], el[2]))
                    elif el[0] == "a":
                        key.append((ELEM_ANY, el[1], el[2]))
                    elif el[0] == "C":
                        # run bounds packed into b: min | max << 8 (0 = open)
                        key.append((ELEM_PUNCT_RUN, el[1], el[2] | (el[3] << 8)))
                    else:  # 'c'
                        key.append((ELEM_PUNCT, el[1], 0))
                pid = self._pattern(tuple(key))
                self.patterns[pid].add(rule_id)
