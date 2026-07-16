"""Pattern compilation: rule files -> element sequences (patterns)."""

import re
import sys
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from .constants import ELEM_GAP, ELEM_PREFIX, ELEM_PUNCT, ELEM_WORD, MAX_COMBOS, MAX_GAP, NONE
from .normalize import is_word_char, normalize, word_variants
from .rule_file import expand_brackets, parse_rule_file, split_tokens

if TYPE_CHECKING:
    from pymorphy3 import MorphAnalyzer

COMMA_RULE_RE = re.compile(r"^_(\s*,\s*_)+$")
GAP_RE = re.compile(r"^_(?:\((\d+)(?:-(\d+))?\))?$")

# ("w", form) | ("p", stem) | ("g", lo, hi) | ("c", codepoint)
type Element = tuple[str, str] | tuple[str, int, int] | tuple[str, int]
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
        self.comma_rule_id = NONE
        self.comma_threshold = 0
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
            raise SystemExit(f"{ctx}: empty word in pattern")
        for ch in word:
            if not is_word_char(ch):
                raise SystemExit(f"{ctx}: character {ch!r} cannot appear in a word")
        if word[0] in "-'" or word[-1] in "-'":
            raise SystemExit(f"{ctx}: word cannot start/end with a connector: {word!r}")

    def expand_lexeme(self, word: str, ctx: str) -> list[str]:
        if self.morph is None:
            raise SystemExit(
                f"{ctx}: '~' morphology expansion is only available for Russian"
                " rules (pymorphy3); use a prefix pattern (основ*) instead"
            )
        parses = self.morph.parse(word)
        if not parses:
            raise SystemExit(f"{ctx}: pymorphy3 cannot parse {word!r}")
        forms = {normalize(f.word) for f in parses[0].lexeme}
        forms.add(normalize(word))
        return sorted(forms)

    # --- pattern line -> element sequences ------------------------------------

    def word_elements(self, word: str, ctx: str) -> list[Element]:
        """One plain word (no brackets, no gaps) -> list of single elements."""
        if word.startswith("~") and word.endswith("*"):
            # the prefix already covers every inflected form
            print(
                f"note: {ctx}: {word!r} compiled as prefix {word[1:]!r}",
                file=sys.stderr,
            )
            word = word[1:]
        if word.startswith("~"):
            forms = self.expand_lexeme(normalize(word[1:]), ctx)
            for f in forms:
                self._validate_word(f, ctx)
            self.form_count += len(forms)
            return [("w", f) for f in forms]
        if word.endswith("*"):
            stem = normalize(word[:-1])
            if "*" in stem:
                raise SystemExit(
                    f"{ctx}: '*' is only valid at the end of a word;"
                    f" for an optional apostrophe use don['|’]?t: {word!r}"
                )
            self._validate_word(stem, ctx)
            return [("p", v) for v in word_variants(stem)]
        if "*" in word:
            raise SystemExit(
                f"{ctx}: '*' is only valid at the end of a word;"
                f" for an optional apostrophe use don['|’]?t: {word!r}"
            )
        w = normalize(word)
        self._validate_word(w, ctx)
        return [("w", v) for v in word_variants(w)]

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
                raise SystemExit(
                    f"{ctx}: bad gap {tok!r} (need 0 <= min <= max,"
                    f" 1 <= max <= {MAX_GAP})"
                )
            return [[("g", lo, hi)]]
        if tok.startswith("_"):
            raise SystemExit(f"{ctx}: bad gap syntax {tok!r}; use _, _(2) or _(0-3)")
        alts: Slot = []
        for s in expand_brackets(tok, ctx):
            if "?" in s:
                raise SystemExit(f"{ctx}: '?' is only valid right after ']': {tok!r}")
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
        if not any(k in ("w", "p") for k in kinds):
            raise SystemExit(f"{ctx}: pattern needs at least one word: {line!r}")
        if kinds[0] not in ("w", "p"):
            raise SystemExit(
                f"{ctx}: pattern cannot start with a gap or punctuation: {line!r}"
            )
        if kinds[-1] == "g":
            raise SystemExit(f"{ctx}: pattern cannot end with a gap: {line!r}")
        for a, b in zip(kinds, kinds[1:]):
            if a == "g" and b == "g":
                raise SystemExit(
                    f"{ctx}: adjacent gaps; merge them into one _(n-m): {line!r}"
                )

    def add_rule_file(self, path: Path) -> None:
        meta, lines = parse_rule_file(path)
        title = meta.get("title", path.stem)
        description = meta.get("description", "")
        try:
            weight = int(meta.get("weight", "0"))
        except ValueError:
            raise SystemExit(f"{path}: weight must be an integer")
        rule_id = len(self.rules)
        self.rules.append(
            {"title": title, "description": description, "weight": weight}
        )

        for n, raw in enumerate(lines, 1):
            ctx = f"{path}:{n}"
            line = raw.strip()
            if COMMA_RULE_RE.match(line):
                self.comma_rule_id = rule_id
                self.comma_threshold = line.count(",")
                continue
            if "*" in line and re.search(r"(^|\s)\*(\s|$|,)", line):
                raise SystemExit(
                    f"{ctx}: standalone '*' is gone; use '_' for any word"
                    f" (comma rule: '_, _, ...'): {line!r}"
                )

            slots = self.line_slots(line, ctx)
            if not slots:
                raise SystemExit(f"{ctx}: empty pattern")
            combos = 1
            for slot in slots:
                combos *= len(slot)
            if combos > MAX_COMBOS:
                raise SystemExit(
                    f"{ctx}: too many form combinations ({combos}) in {line!r}"
                )
            for combo in product(*slots):
                seq = [el for alt in combo for el in alt]
                self._check_sequence(seq, ctx, line)
                key: list[tuple[int, int, int]] = []
                for el in seq:
                    if el[0] == "w":
                        key.append((ELEM_WORD, self.word_id(el[1]), 0))
                    elif el[0] == "p":
                        key.append((ELEM_PREFIX, self.prefix_id(el[1]), 0))
                    elif el[0] == "g":
                        key.append((ELEM_GAP, el[1], el[2]))
                    else:  # 'c'
                        key.append((ELEM_PUNCT, el[1], 0))
                pid = self._pattern(tuple(key))
                self.patterns[pid].add(rule_id)
