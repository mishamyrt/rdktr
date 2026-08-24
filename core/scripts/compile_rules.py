#!/usr/bin/env python3
r"""rdktr rules compiler.

Reads rule files (rules/<lang>/*.md), expands markers and builds one binary
blob per language: a double-array trie (exact words + prefix stems) and a
pattern table (element sequences matched by the engine at scan time). The
blobs are embedded into the C library as a generated source file.

The implementation lives in the rules_compiler package next to this script.

Usage:
    python3 compile_rules.py [--rules DIR] [--out-c FILE] [--out-bin-dir DIR]

To lint the rules without compiling, use lint_rules.py.
"""

import argparse
from pathlib import Path

import pymorphy3

from rules_compiler.compiler import Compiler
from rules_compiler.rule_file import RuleError
from rules_compiler.serialize import build_blob, emit_c



def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rules", default=str(root / "rules"),
                    help="directory with per-language subdirectories")
    ap.add_argument("--out-c", default=str(root / "src" / "rules_data.c"))
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
        if lang == "ru":
            morph = pymorphy3.MorphAnalyzer()
        comp = Compiler(lang, morph if lang == "ru" else None)
        for f in sorted(lang_dir.glob("*.md")):
            try:
                comp.add_rule_file(f)
            except RuleError as e:
                raise SystemExit(str(e))
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
