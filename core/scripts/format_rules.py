#!/usr/bin/env python3
r"""rdktr rules formatter.

Lowercases every pattern and sorts the patterns in each rule file
alphabetically, ignoring syntax markers (`~`, `*`, `_`, brackets, …). Front
matter is left untouched.

Usage:
    python3 format_rules.py [rules_dir] [--check]

With --check the files are not modified: the command lists any file that is
not already formatted and exits non-zero (useful in CI).
"""

import argparse
from pathlib import Path

from rules_compiler.formatter import format_file, format_text
from rules_compiler.rule_file import RuleError


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rules", nargs="?", default=str(root / "rules"),
                    help="directory with per-language subdirectories")
    ap.add_argument("--check", action="store_true",
                    help="don't write; exit non-zero if any file needs formatting")
    args = ap.parse_args()

    lang_dirs = sorted(
        d for d in Path(args.rules).iterdir() if d.is_dir() and list(d.glob("*.md"))
    )
    if not lang_dirs:
        raise SystemExit(f"no language directories with rules found in {args.rules}")

    unformatted: list[Path] = []
    for lang_dir in lang_dirs:
        for f in sorted(lang_dir.glob("*.md")):
            try:
                if args.check:
                    if format_text(f.read_text(encoding="utf-8"), str(f)) \
                            != f.read_text(encoding="utf-8"):
                        unformatted.append(f)
                elif not format_file(f):
                    unformatted.append(f)
            except RuleError as e:
                raise SystemExit(str(e))

    if args.check:
        if unformatted:
            print("not formatted:")
            for f in unformatted:
                print(f"  {f}")
            raise SystemExit(1)
        print("all rules formatted")
    else:
        if unformatted:
            print(f"formatted {len(unformatted)} file(s):")
            for f in unformatted:
                print(f"  {f}")
        else:
            print("all rules already formatted")


if __name__ == "__main__":
    main()
