#!/usr/bin/env python3
r"""rdktr rules linter.

Checks that rules are valid and consistent.

Usage:
    python3 lint_rules.py [rules_dir]
"""

import argparse
import os
import sys
from pathlib import Path

import pymorphy3

from rules_compiler.linter import Linter, render

def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rules", nargs="?", default=str(root / "rules"),
                    help="directory with per-language subdirectories")
    args = ap.parse_args()

    lang_dirs = sorted(
        d for d in Path(args.rules).iterdir() if d.is_dir() and list(d.glob("*.md"))
    )
    if not lang_dirs:
        raise SystemExit(f"no language directories with rules found in {args.rules}")

    rules_root = Path(args.rules).resolve()
    diags = []
    for lang_dir in lang_dirs:
        lang = lang_dir.name
        morph = pymorphy3.MorphAnalyzer() if lang == "ru" else None
        linter = Linter(lang, morph, root=rules_root)
        for f in sorted(lang_dir.glob("*.md")):
            linter.lint_file(f.resolve())
        linter.report_duplicates()
        diags += linter.diagnostics

    color = (
        sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and os.environ.get("TERM") != "dumb"
    )
    print(render(diags, color))
    if any(d.kind != "warn" for d in diags):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
