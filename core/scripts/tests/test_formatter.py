"""Formatter unit tests: sort key, lowercasing, front-matter preservation."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules_compiler.formatter import format_text, lower_pattern, sort_key
from rules_compiler.rule_file import RuleError

META = "---\ntitle: t\ndescription: d.\nweight: 1\n---\n"


def body(text: str) -> list[str]:
    return format_text(META + "\n" + text, "t").split("\n---\n\n", 1)[1].splitlines()


def test_sort_key_drops_syntax_markers():
    assert sort_key("~сомнительное ~удовольствие") == "сомнительное удовольствие"
    assert sort_key("этот _ гвоздь") == "этот гвоздь"
    assert sort_key("энерги*") == "энерги"
    assert sort_key("[в]? личной жизни") == "в личной жизни"


def test_sort_key_lowercases():
    assert sort_key("~Пресловутый") == "~пресловутый".lstrip("~")
    assert sort_key("SOMEWHAT") == "somewhat"


def test_sort_key_ignores_lint_ignore_marker():
    assert sort_key("абв # lint-ignore: typo") == "абв"


def test_sort_ignores_tilde():
    # ~беда must sort by "беда" (after "азарт", before "весна")
    assert body("~беда\nвесна\nазарт") == ["азарт", "~беда", "весна"]


def test_lowercasing_of_patterns():
    assert body("Направо И Налево") == ["направо и налево"]


def test_lower_pattern_preserves_marker_tags():
    assert lower_pattern("~НЕПРИНЦИПиальн # lint-ignore: typo") == \
        "~непринципиальн # lint-ignore: typo"


def test_front_matter_preserved_verbatim():
    out = format_text(META + "\nбаба\nаба\n", "t")
    assert out.startswith(META)
    assert out == META + "\nаба\nбаба\n"


def test_idempotent():
    once = format_text(META + "\nвесна\nазарт\n~беда\n", "t")
    assert format_text(once, "t") == once


def test_missing_front_matter():
    with pytest.raises(RuleError):
        format_text("no front matter\n", "t")
