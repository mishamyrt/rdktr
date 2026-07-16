#!/usr/bin/env python3
"""rdktr rules compiler.

Reads rule files (rules/<lang>/*.md), expands markers and builds one binary
blob per language: a double-array trie (exact words + prefix stems) and a
pattern table (element sequences matched by the engine at scan time). The
blobs are embedded into the C library as a generated source file.

The implementation lives in the rules_compiler package next to this script.

Pattern line syntax (see rules/README.md):
    слово или фраза      exact match (case-insensitive, ё == е)
    ~слово               all inflected forms of the lexeme
                         (pymorphy3; Russian rules only); works inside phrases
    основ*               prefix: the stem plus at least one more letter;
                         works inside phrases
    [гвоздь|гвозди]      alternatives; inside a word: don['|’]t
    [в]? слово           '?' right after ']' makes the alternative optional
    этот _ гвоздь        gap: exactly one arbitrary word
    этот _(2) гвоздь     gap: exactly two arbitrary words
    этот _(0-3) гвоздь   gap: zero to three arbitrary words
    казалось,            ',' must appear in the text at this position
    _, _, _, _, _, _     special structural rule: too many commas in a sentence

Usage:
    python3 compile_rules.py [--rules DIR] [--out-c FILE] [--out-bin-dir DIR]
"""

import argparse
from pathlib import Path

from rules_compiler.compiler import Compiler
from rules_compiler.serialize import build_blob, emit_c


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rules", default=str(root / "rules"),
                    help="directory with per-language subdirectories")
    ap.add_argument("--out-c", default=str(root / "core" / "src" / "rules_data.c"))
    ap.add_argument("--out-bin-dir", default=None,
                    help="optionally also write rules_<lang>.bin files here")
    args = ap.parse_args()

    lang_dirs = sorted(
        d for d in Path(args.rules).iterdir() if d.is_dir() and list(d.glob("*.md"))
    )
    if not lang_dirs:
        raise SystemExit(f"no language directories with rules found in {args.rules}")

    morph = None
    blobs: list[tuple[str, bytes]] = []
    for lang_dir in lang_dirs:
        lang = lang_dir.name
        if lang == "ru" and morph is None:
            try:
                import pymorphy3
            except ImportError:
                raise SystemExit(
                    "pymorphy3 is required: pip install -r tools/requirements.txt"
                )
            morph = pymorphy3.MorphAnalyzer()

        comp = Compiler(lang, morph if lang == "ru" else None)
        for f in sorted(lang_dir.glob("*.md")):
            comp.add_rule_file(f)
        blob = build_blob(comp)
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
