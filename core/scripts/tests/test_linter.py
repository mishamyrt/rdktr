"""Linter unit tests: duplicate grouping, advice branches, lint-ignore."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules_compiler.linter import Diagnostic, Linter, render


class FakeParse:
    def __init__(self, forms: list[str]):
        self.lexeme = [type("F", (), {"word": f}) for f in forms]


class FakeMorph:
    """pymorphy3 stand-in: fixed inflection tables + dictionary lookup."""

    TABLES = {
        "гвоздь": ["гвоздь", "гвоздя", "гвозди", "гвоздей"],
        "гвоздя": ["гвоздя"],  # single-form lexeme inside гвоздь's paradigm
        "синий": ["синий", "синяя", "синие"],
        "однако": ["однако"],
        # partial overlap pair: share the form "планы"
        "план": ["план", "планы"],
        "планы": ["планы", "планов"],
    }

    def parse(self, word: str):
        return [FakeParse(self.TABLES.get(word, [word]))]

    def word_is_known(self, word: str) -> bool:
        return word in self.TABLES


META = "---\ntitle: t\ndescription: d.\nweight: 1\n---\n\n"


def lint_files(tmp_path: Path, files: dict[str, str]) -> list[Diagnostic]:
    linter = Linter("ru", FakeMorph(), root=tmp_path)
    for name, body in files.items():
        f = tmp_path / name
        f.write_text(META + body, encoding="utf-8")
        linter.lint_file(f)
    linter.report_duplicates()
    return linter.diagnostics


def lint_lines(tmp_path: Path, body: str) -> list[Diagnostic]:
    return lint_files(tmp_path, {"rule.md": body})


def test_clean_file(tmp_path: Path) -> None:
    assert lint_lines(tmp_path, "гвоздь\nзабить ~гвоздь\n") == []


def test_missing_description(tmp_path: Path) -> None:
    linter = Linter("ru", FakeMorph())
    f = tmp_path / "rule.md"
    f.write_text("---\ntitle: t\n---\nгвоздь\n", encoding="utf-8")
    linter.lint_file(f)
    (d,) = linter.diagnostics
    assert d.kind == "meta" and "description" in d.message


def test_description_without_period(tmp_path: Path) -> None:
    linter = Linter("ru", FakeMorph())
    f = tmp_path / "rule.md"
    f.write_text("---\ntitle: t\ndescription: без точки\n---\nгвоздь\n",
                 encoding="utf-8")
    linter.lint_file(f)
    (d,) = linter.diagnostics
    assert d.kind == "meta" and "period" in d.message


def test_syntax_error_has_real_line_number(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "гвоздь\n\n\nэтот _\n")
    (d,) = diags
    # META is 6 lines, body starts at 7; the bad line is body line 4 -> 10
    assert d.kind == "syntax" and d.line == 10
    assert "cannot end with a gap" in d.message


def test_duplicate_word_subset_advice(tmp_path: Path) -> None:
    diags = lint_files(
        tmp_path, {"a.md": "гвоздь\n", "b.md": "~гвоздь\n"}
    )
    (d,) = diags
    assert d.kind == "dup"
    assert "duplicate word 'гвоздь'" in d.message
    assert "keep '~гвоздь' (4 words)" in d.message
    assert "drop a.md:7" in d.message


def test_duplicate_identical_lines_advice(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "~гвоздь\n~гвоздь\n")
    (d,) = diags
    assert "4 duplicate words" in d.message
    assert "keep either one" in d.message


def test_duplicate_partial_overlap_advice(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "~план\n~планы\n")
    (d,) = diags
    assert "duplicate word 'планы'" in d.message
    assert "neither covers the other" in d.message
    assert "'~план' 2" in d.message and "'~планы' 2" in d.message


def test_shrink_advice_for_self_overlap(tmp_path: Path) -> None:
    # ~гвоздь covers ~гвоздя (unknown word -> single-form paradigm)
    diags = lint_lines(tmp_path, "~гвозд[ь|я]\n")
    (d,) = diags
    assert "same 4 words with just '~гвоздь'" in d.message


def test_duplicate_pattern_expansion(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "забить гвоздь\nзабить гвозд[ь|и]\n")
    (d,) = diags
    assert d.kind == "dup" and "1 duplicate pattern expansion" in d.message


def test_typo_is_error(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "~шуруп\n")
    (d,) = diags
    assert d.kind == "typo" and "'шуруп' is not in the morphological" in d.message


def test_lint_ignore_suppresses_typo(tmp_path: Path) -> None:
    assert lint_lines(tmp_path, "~шуруп # lint-ignore: typo\n") == []


def test_unknown_lint_ignore_tag_warns(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "гвоздь # lint-ignore: tpyo\n")
    (d,) = diags
    assert d.kind == "warn" and "unknown lint-ignore tag 'tpyo'" in d.message


def test_malformed_lint_ignore_is_clear_error(tmp_path: Path) -> None:
    diags = lint_lines(tmp_path, "гвоздь # lint-ignore:\n")
    (d,) = diags
    assert d.kind == "syntax" and "malformed lint-ignore marker" in d.message


def test_render_groups_and_summary(tmp_path: Path) -> None:
    diags = lint_files(
        tmp_path, {"a.md": "гвоздь\n", "b.md": "~гвоздь\n~шуруп\n"}
    )
    text = render(diags, color=False)
    assert "a.md" in text.splitlines()[0]
    assert "✖ 2 problems (1 dup, 1 typo)" in text
    assert render([], color=False) == "✓ rules are clean"
