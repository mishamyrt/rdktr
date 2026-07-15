#!/usr/bin/env python3
"""rdktr rules compiler.

Reads rule files (Rules/<lang>/*.md), expands morphology markers and builds
one binary blob per language, each with a double-array trie (pattern words)
and a phrase automaton (Aho-Corasick over word ids). The blobs are embedded
into the C library as a generated source file.

Pattern line syntax:
    слово или фраза      exact match (case-insensitive, ё == е)
    ~слово               expand to all inflected forms of the lexeme
                         (pymorphy3; Russian rules only)
    основ*               prefix match: any word starting with "основ"
    *, *, *, *, *, *     special structural rule: too many commas in a sentence

Usage:
    python3 compile_rules.py [--rules DIR] [--out-c FILE] [--out-bin-dir DIR]
"""

import argparse
import re
import struct
import sys
from pathlib import Path

NONE = 0xFFFFFFFF
HEADER_SIZE = 104
MAGIC = b"RDK1"
VERSION = 2

COMMA_RULE_RE = re.compile(r"^\*(\s*,\s*\*)+$")

# --- Normalization (must mirror Sources/CRdktr/normalize.c exactly) ---------


def normalize(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0x41 <= o <= 0x5A:  # A-Z
            ch = chr(o + 0x20)
        elif 0x410 <= o <= 0x42F:  # А-Я
            ch = chr(o + 0x20)
        elif o in (0x401, 0x451):  # Ё, ё
            ch = "е"
        out.append(ch)
    return "".join(out)


def is_word_char(ch: str) -> bool:
    """Mirror of is_word_core() in engine.c plus in-word connectors."""
    o = ord(ch)
    if o < 0x80:
        return ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "-'"
    if o == 0x2019:  # ’ typographic apostrophe (connector)
        return True
    if 0x400 <= o <= 0x4FF:
        return True
    if 0xC0 <= o <= 0x24F and o not in (0xD7, 0xF7):
        return True
    return False


def word_variants(word: str):
    """don't / don’t are different byte sequences; index both."""
    if "'" in word:
        return [word, word.replace("'", "’")]
    if "’" in word:
        return [word.replace("’", "'"), word]
    return [word]


def apostrophe_star_variants(word: str, ctx: str):
    """Mid-word '*' marks an optional apostrophe:
    don*t -> dont, don't, don’t."""
    if "*" not in word:
        return word_variants(word)
    from itertools import product

    parts = word.split("*")
    if any(p == "" for p in parts):
        raise SystemExit(
            f"{ctx}: '*' inside a word marks an optional apostrophe and"
            f" cannot start or end the word: {word!r}"
        )
    out = []
    for seps in product(["", "'", "’"], repeat=len(parts) - 1):
        w = parts[0]
        for sep, part in zip(seps, parts[1:]):
            w = w + sep + part
        out.append(w)
    return out


# --- Rule file parsing -------------------------------------------------------


def parse_rule_file(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise SystemExit(f"{path}: missing front matter")
    meta = {}
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


# --- Double-array trie -------------------------------------------------------


class Trie:
    def __init__(self):
        self.children = [{}]  # node -> {byte: node}
        self.word_id = [NONE]
        self.prefix_pat = [NONE]

    def _walk_insert(self, key: bytes) -> int:
        node = 0
        for b in key:
            nxt = self.children[node].get(b)
            if nxt is None:
                nxt = len(self.children)
                self.children.append({})
                self.word_id.append(NONE)
                self.prefix_pat.append(NONE)
                self.children[node][b] = nxt
            node = nxt
        return node

    def insert_word(self, word: str, wid: int):
        node = self._walk_insert(word.encode("utf-8"))
        assert self.word_id[node] in (NONE, wid)
        self.word_id[node] = wid

    def insert_prefix(self, prefix: str, pat: int):
        node = self._walk_insert(prefix.encode("utf-8"))
        assert self.prefix_pat[node] in (NONE, pat)
        self.prefix_pat[node] = pat

    def build_double_array(self):
        """Returns (base, check, wid, ppat) arrays. Slot 0 is the root."""
        size = 1024
        base = [0] * size
        check = [NONE] * size
        wid = [NONE] * size
        ppat = [NONE] * size

        def ensure(n):
            nonlocal size
            while size < n:
                size *= 2
            while len(base) < size:
                base.append(0)
                check.append(NONE)
                wid.append(NONE)
                ppat.append(NONE)

        slot_of = {0: 0}
        wid[0] = self.word_id[0]
        ppat[0] = self.prefix_pat[0]
        search_hint = 1
        queue = [0]
        while queue:
            node = queue.pop(0)
            kids = self.children[node]
            if not kids:
                continue
            bytes_ = sorted(kids.keys())
            s = slot_of[node]
            b = max(1, search_hint - bytes_[0])
            while True:
                ensure(b + 256 + 1)
                if all(check[b + c] == NONE for c in bytes_):
                    break
                b += 1
            base[s] = b
            for c in bytes_:
                t = b + c
                child = kids[c]
                check[t] = s
                wid[t] = self.word_id[child]
                ppat[t] = self.prefix_pat[child]
                slot_of[child] = t
                queue.append(child)
            # advance hint past fully occupied region
            while search_hint < size and check[search_hint] != NONE:
                search_hint += 1
        used = max((i for i in range(size) if check[i] != NONE), default=0)
        n = used + 1
        return base[:n], check[:n], wid[:n], ppat[:n]

    @staticmethod
    def lookup(base, check, word: bytes):
        s = 0
        for b in word:
            t = base[s] + b
            if t >= len(check) or check[t] != s:
                return None
            s = t
        return s


# --- Aho-Corasick over word ids ---------------------------------------------


class PhraseAutomaton:
    def __init__(self):
        self.trans = [{}]  # state -> {word_id: state}
        self.out = [[]]  # state -> [(pattern_id, tok_len)]
        self.fail = [0]

    def add(self, word_ids, pattern_id):
        s = 0
        for w in word_ids:
            nxt = self.trans[s].get(w)
            if nxt is None:
                nxt = len(self.trans)
                self.trans.append({})
                self.out.append([])
                self.fail.append(0)
                self.trans[s][w] = nxt
            s = nxt
        pair = (pattern_id, len(word_ids))
        if pair not in self.out[s]:
            self.out[s].append(pair)

    def build_fail_links(self):
        from collections import deque

        q = deque()
        for w, t in self.trans[0].items():
            self.fail[t] = 0
            q.append(t)
        while q:
            s = q.popleft()
            for w, t in self.trans[s].items():
                f = self.fail[s]
                while f != 0 and w not in self.trans[f]:
                    f = self.fail[f]
                nxt = self.trans[f].get(w, 0)
                self.fail[t] = nxt if nxt != t else 0
                for pair in self.out[self.fail[t]]:
                    if pair not in self.out[t]:
                        self.out[t].append(pair)
                q.append(t)


# --- Compilation -------------------------------------------------------------


class Compiler:
    def __init__(self, lang: str, morph=None):
        if not (1 <= len(lang) <= 3) or not lang.isascii() or not lang.isalpha():
            raise SystemExit(f"language code must be 1-3 ASCII letters, got {lang!r}")
        self.lang = lang.lower()
        self.morph = morph
        self.rules = []  # {title, description, weight}
        self.word_ids = {}  # word -> id
        self.patterns = []  # pattern_id -> set(rule_ids)
        self.pattern_by_key = {}  # key -> pattern_id
        self.seq_patterns = {}  # tuple(word_ids) -> pattern_id
        self.comma_rule_id = NONE
        self.comma_threshold = 0
        self.form_count = 0

    def word_id(self, word: str) -> int:
        wid = self.word_ids.get(word)
        if wid is None:
            wid = len(self.word_ids)
            self.word_ids[word] = wid
        return wid

    def _pattern(self, key) -> int:
        pid = self.pattern_by_key.get(key)
        if pid is None:
            pid = len(self.patterns)
            self.pattern_by_key[key] = pid
            self.patterns.append(set())
        return pid

    def _validate_word(self, word: str, ctx: str):
        if not word:
            raise SystemExit(f"{ctx}: empty word in pattern")
        for ch in word:
            if not is_word_char(ch):
                raise SystemExit(f"{ctx}: character {ch!r} cannot appear in a word")
        if word[0] in "-'" or word[-1] in "-'":
            raise SystemExit(f"{ctx}: word cannot start/end with a connector: {word!r}")

    def add_seq(self, words, rule_id, ctx):
        from itertools import product

        for w in words:
            self._validate_word(w, ctx)
        for combo in product(*(word_variants(w) for w in words)):
            ids = tuple(self.word_id(w) for w in combo)
            pid = self._pattern(("seq", ids))
            self.patterns[pid].add(rule_id)
            self.seq_patterns[ids] = pid

    def add_prefix(self, prefix, rule_id, ctx):
        self._validate_word(prefix, ctx)
        for variant in word_variants(prefix):
            pid = self._pattern(("prefix", variant))
            self.patterns[pid].add(rule_id)

    def expand_lexeme(self, word: str, ctx: str):
        if self.morph is None:
            raise SystemExit(
                f"{ctx}: '~' morphology expansion is only available for Russian"
                " rules (pymorphy3); use a prefix pattern (word*) instead"
            )
        parses = self.morph.parse(word)
        if not parses:
            raise SystemExit(f"{ctx}: pymorphy3 cannot parse {word!r}")
        forms = {normalize(f.word) for f in parses[0].lexeme}
        forms.add(normalize(word))
        return sorted(forms)

    def add_rule_file(self, path: Path):
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
        from itertools import product

        for n, raw in enumerate(lines, 1):
            ctx = f"{path}:{n}"
            line = raw.strip()
            if COMMA_RULE_RE.match(line):
                self.comma_rule_id = rule_id
                self.comma_threshold = line.count(",")
                continue

            words_raw = line.split()

            # single-word prefix patterns go into the trie as prefix terminals
            if len(words_raw) == 1 and words_raw[0].endswith("*"):
                w = words_raw[0]
                if w.startswith("~"):
                    # combined markers: the prefix already covers every
                    # inflected form, so compile it as a plain prefix
                    print(
                        f"note: {ctx}: {line!r} compiled as prefix {w[1:]!r}",
                        file=sys.stderr,
                    )
                    w = w[1:]
                for stem in apostrophe_star_variants(normalize(w[:-1]), ctx):
                    self.add_prefix(stem, rule_id, ctx)
                continue

            # words and phrases; each word may carry a ~ marker, which
            # expands to every inflected form (cartesian product for phrases)
            variant_lists = []
            for w in words_raw:
                if w.endswith("*"):
                    raise SystemExit(
                        f"{ctx}: prefix inside a phrase is not supported;"
                        f" use '~лемма' to match all forms: {line!r}"
                    )
                if w.startswith("~"):
                    if "*" in w:
                        raise SystemExit(
                            f"{ctx}: markers '~' and '*' cannot be combined"
                            f" inside a word: {w!r}"
                        )
                    forms = self.expand_lexeme(normalize(w[1:]), ctx)
                    self.form_count += len(forms)
                    variant_lists.append(forms)
                else:
                    variant_lists.append(
                        apostrophe_star_variants(normalize(w), ctx)
                    )
            combos = 1
            for vl in variant_lists:
                combos *= len(vl)
            if combos > 4096:
                raise SystemExit(
                    f"{ctx}: too many form combinations ({combos}) in {line!r}"
                )
            for combo in product(*variant_lists):
                self.add_seq(list(combo), rule_id, ctx)

    # --- serialization -------------------------------------------------------

    def build_blob(self) -> bytes:
        # word trie
        trie = Trie()
        for word, wid in self.word_ids.items():
            trie.insert_word(word, wid)
        for (kind, key), pid in self.pattern_by_key.items():
            if kind == "prefix":
                trie.insert_prefix(key, pid)
        base, check, wid_arr, ppat_arr = trie.build_double_array()

        # self-check: every word and prefix must be reachable
        for word, wid in self.word_ids.items():
            slot = Trie.lookup(base, check, word.encode("utf-8"))
            assert slot is not None and wid_arr[slot] == wid, f"DAT broken for {word!r}"
        for (kind, key), pid in self.pattern_by_key.items():
            if kind == "prefix":
                slot = Trie.lookup(base, check, key.encode("utf-8"))
                assert slot is not None and ppat_arr[slot] == pid

        # phrase automaton
        ac = PhraseAutomaton()
        max_len = 1
        for ids, pid in self.seq_patterns.items():
            ac.add(ids, pid)
            max_len = max(max_len, len(ids))
        ac.build_fail_links()

        # string pool (deduplicated, NUL-terminated)
        pool = bytearray()
        pool_offsets = {}

        def intern(s: str) -> int:
            if s not in pool_offsets:
                pool_offsets[s] = len(pool)
                pool.extend(s.encode("utf-8") + b"\0")
            return pool_offsets[s]

        rule_entries = [
            (intern(r["title"]), intern(r["description"]), r["weight"])
            for r in self.rules
        ]

        # pattern rule lists (flattened)
        pat_entries = []
        pat_rules = []
        for rules in self.patterns:
            pat_entries.append((len(pat_rules), len(rules)))
            pat_rules.extend(sorted(rules))

        # AC serialization: transitions sorted by word_id per state
        ac_states = []
        ac_trans = []
        ac_out = []
        for s in range(len(ac.trans)):
            t_start = len(ac_trans)
            for w in sorted(ac.trans[s]):
                ac_trans.append((w, ac.trans[s][w]))
            o_start = len(ac_out)
            for pid, tok_len in sorted(ac.out[s], key=lambda p: (-p[1], p[0])):
                ac_out.append((pid, tok_len))
            ac_states.append(
                (t_start, len(ac.trans[s]), ac.fail[s], o_start, len(ac.out[s]))
            )

        # --- assemble sections ---
        def align4(buf: bytearray):
            while len(buf) % 4:
                buf.append(0)

        body = bytearray(HEADER_SIZE)

        def section(fmt_items):
            align4(body)
            off = len(body)
            body.extend(fmt_items)
            return off

        rules_off = section(
            b"".join(struct.pack("<III", *e) for e in rule_entries)
        )
        strpool_off = section(bytes(pool) if pool else b"\0")
        strpool_size = len(pool) if pool else 1
        dat_base_off = section(struct.pack(f"<{len(base)}I", *base))
        dat_check_off = section(struct.pack(f"<{len(check)}I", *check))
        dat_wordid_off = section(struct.pack(f"<{len(wid_arr)}I", *wid_arr))
        dat_prefixpat_off = section(struct.pack(f"<{len(ppat_arr)}I", *ppat_arr))
        pat_off = section(b"".join(struct.pack("<II", *e) for e in pat_entries))
        pat_rules_off = section(struct.pack(f"<{len(pat_rules)}I", *pat_rules))
        ac_states_off = section(
            b"".join(struct.pack("<IIIII", *e) for e in ac_states)
        )
        ac_trans_off = section(
            b"".join(struct.pack("<II", *e) for e in ac_trans)
        )
        ac_out_off = section(b"".join(struct.pack("<II", *e) for e in ac_out))
        align4(body)

        header = struct.pack(
            "<4sIIIIIIIIIIIIIIIIIIIIIIII4s",
            MAGIC,
            VERSION,
            len(body),
            len(self.rules),
            rules_off,
            strpool_off,
            strpool_size,
            len(base),
            dat_base_off,
            dat_check_off,
            dat_wordid_off,
            dat_prefixpat_off,
            len(self.patterns),
            pat_off,
            pat_rules_off,
            len(pat_rules),
            len(ac_states),
            ac_states_off,
            ac_trans_off,
            len(ac_trans),
            ac_out_off,
            len(ac_out),
            max_len,
            self.comma_rule_id,
            self.comma_threshold,
            self.lang.encode("ascii").ljust(4, b"\0"),
        )
        assert len(header) == HEADER_SIZE, len(header)
        body[:HEADER_SIZE] = header

        self.stats = {
            "rules": len(self.rules),
            "words": len(self.word_ids),
            "expanded_forms": self.form_count,
            "patterns": len(self.patterns),
            "dat_slots": len(base),
            "ac_states": len(ac_states),
            "blob_bytes": len(body),
        }
        return bytes(body)


C_HEADER = """\
/* Generated by Scripts/compile_rules.py — do not edit by hand.
 * Regenerate with: python3 Scripts/compile_rules.py
 */
#include "rdktr_internal.h"
"""

C_FOOTER = """\
const rdktr_embedded_ruleset rdktr_embedded_rulesets[] = {{
{entries}
}};

const size_t rdktr_embedded_ruleset_count = {count};
"""


def emit_c(blobs, path: Path):
    """blobs: list of (lang, bytes)."""
    parts = [C_HEADER]
    for lang, blob in blobs:
        rows = []
        for i in range(0, len(blob), 16):
            chunk = blob[i : i + 16]
            rows.append("    " + ", ".join(f"0x{b:02x}" for b in chunk) + ",")
        parts.append(
            f"\n_Alignas(4) static const uint8_t rules_{lang}[] = {{\n"
            + "\n".join(rows)
            + "\n};\n"
        )
    entries = "\n".join(
        f'    {{"{lang}", rules_{lang}, sizeof(rules_{lang})}},' for lang, _ in blobs
    )
    parts.append("\n" + C_FOOTER.format(entries=entries, count=len(blobs)))
    path.write_text("".join(parts), encoding="utf-8")


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rules", default=str(root / "Rules"),
                    help="directory with per-language subdirectories")
    ap.add_argument("--out-c", default=str(root / "Sources" / "CRdktr" / "rules_data.c"))
    ap.add_argument("--out-bin-dir", default=None,
                    help="optionally also write rules_<lang>.bin files here")
    args = ap.parse_args()

    lang_dirs = sorted(
        d for d in Path(args.rules).iterdir() if d.is_dir() and list(d.glob("*.md"))
    )
    if not lang_dirs:
        raise SystemExit(f"no language directories with rules found in {args.rules}")

    morph = None
    blobs = []
    for lang_dir in lang_dirs:
        lang = lang_dir.name
        if lang == "ru" and morph is None:
            try:
                import pymorphy3
            except ImportError:
                raise SystemExit(
                    "pymorphy3 is required: pip install -r Scripts/requirements.txt"
                )
            morph = pymorphy3.MorphAnalyzer()

        comp = Compiler(lang, morph if lang == "ru" else None)
        for f in sorted(lang_dir.glob("*.md")):
            comp.add_rule_file(f)
        blob = comp.build_blob()
        blobs.append((lang, blob))

        print(f"[{lang}]")
        for k, v in comp.stats.items():
            print(f"{k:>16}: {v}")
        if args.out_bin_dir:
            out = Path(args.out_bin_dir) / f"rules_{lang}.bin"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
            print(f"{'bin':>16}: {out}")

    emit_c(blobs, Path(args.out_c))
    print(f"{'output':>16}: {args.out_c}")


if __name__ == "__main__":
    main()
