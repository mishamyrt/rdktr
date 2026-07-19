"""Compiler unit tests: lexeme model and u16 format guards.

Run with: uv run pytest scripts/tests/
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules_compiler.compiler import Compiler
from rules_compiler.rule_file import RuleError
from rules_compiler.constants import (
    ELEM_ANY,
    ELEM_GAP,
    ELEM_LEXEME,
    ELEM_PUNCT,
    ELEM_PUNCT_RUN,
    ELEM_WORD,
    HEADER_SIZE,
    MAX_ANY_SPAN,
    VERSION,
)
from rules_compiler.serialize import build_blob


class FakeParse:
    def __init__(self, forms: list[str]):
        self.lexeme = [type("F", (), {"word": f}) for f in forms]


class FakeMorph:
    """pymorphy3 stand-in: fixed inflection tables."""

    TABLES = {
        "гвоздь": ["гвоздь", "гвоздя", "гвозди", "гвоздей"],
        "синий": ["синий", "синяя", "синие"],
        "однако": ["однако"],
    }

    def parse(self, word: str):
        return [FakeParse(self.TABLES.get(word, [word]))]


def compile_lines(lines: list[str], tmp_path: Path) -> Compiler:
    rule = tmp_path / "rule.md"
    rule.write_text(
        "---\ntitle: t\nweight: 1\n---\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    comp = Compiler("ru", FakeMorph())
    comp.add_rule_file(rule)
    return comp


def test_lexeme_single_element(tmp_path: Path) -> None:
    comp = compile_lines(["~гвоздь"], tmp_path)
    assert len(comp.patterns) == 1
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_LEXEME]
    assert len(comp.lexeme_sets) == 1
    assert len(comp.lexeme_sets[0]) == 4


def test_mid_word_lexeme_keeps_head(tmp_path: Path) -> None:
    comp = compile_lines(["crm-~гвоздь"], tmp_path)
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_LEXEME]
    words = {w for w, i in comp.word_ids.items() if i in comp.lexeme_sets[0]}
    assert words == {"crm-гвоздь", "crm-гвоздя", "crm-гвозди", "crm-гвоздей"}


def test_mid_word_lexeme_single_form(tmp_path: Path) -> None:
    comp = compile_lines(["crm-~однако"], tmp_path)
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_WORD]
    assert "crm-однако" in comp.word_ids


def test_lint_ignore_marker_is_stripped(tmp_path: Path) -> None:
    comp = compile_lines(["~гвоздь # lint-ignore: typo"], tmp_path)
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_LEXEME]  # no '#' punct, no words


def test_double_tilde_is_error(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="at most one '~'"):
        compile_lines(["~гвоздь-~гвоздь"], tmp_path)


def test_trailing_tilde_is_error(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="must be followed by a word"):
        compile_lines(["crm-~"], tmp_path)


def test_lexeme_phrase_no_product(tmp_path: Path) -> None:
    comp = compile_lines(["~синий ~гвоздь"], tmp_path)
    assert len(comp.patterns) == 1  # was 3 x 4 patterns with expansion
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_LEXEME, ELEM_LEXEME]


def test_identical_sets_dedup(tmp_path: Path) -> None:
    comp = compile_lines(["~гвоздь", "забить ~гвоздь"], tmp_path)
    assert len(comp.lexeme_sets) == 1


def test_single_form_degrades_to_word(tmp_path: Path) -> None:
    comp = compile_lines(["~однако"], tmp_path)
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_WORD]
    assert not comp.lexeme_sets


def test_gap_then_lexeme(tmp_path: Path) -> None:
    comp = compile_lines(["забить _ ~гвоздь"], tmp_path)
    (key,) = comp.pattern_keys
    assert [k for k, _, _ in key] == [ELEM_WORD, ELEM_GAP, ELEM_LEXEME]


def test_lexeme_initial_pattern_seeded_per_form(tmp_path: Path) -> None:
    comp = compile_lines(["~гвоздь забить"], tmp_path)
    blob = build_blob(comp)
    assert blob[:4] == b"RDK1"
    assert struct.unpack_from("<I", blob, 4)[0] == VERSION
    assert len(blob) % 4 == 0
    # one start_list entry per member form of the initial lexeme
    start_list_count = struct.unpack_from("<I", blob, 92)[0]
    assert start_list_count == len(comp.lexeme_sets[0])
    assert struct.unpack_from("<I", blob, 96)[0] == 1  # lexeme_count


def test_u16_overflow_is_hard_error(tmp_path: Path) -> None:
    comp = compile_lines(["~гвоздь"], tmp_path)
    for i in range(0x10000):
        comp.word_id(f"w{i}")
    with pytest.raises(SystemExit, match="blob format overflow"):
        build_blob(comp)


def test_header_size_constant() -> None:
    assert HEADER_SIZE == 136


# --- punctuation literals, repeats and the wide gap -------------------------


def test_punct_run_open_range(tmp_path: Path) -> None:
    comp = compile_lines(["!(2+)"], tmp_path)
    (key,) = comp.pattern_keys
    assert key == ((ELEM_PUNCT_RUN, ord("!"), 2), )  # max 0 = unbounded


def test_punct_run_exact_and_range(tmp_path: Path) -> None:
    comp = compile_lines(["!(3)", r"\?(2-5)"], tmp_path)
    assert comp.pattern_keys[0] == ((ELEM_PUNCT_RUN, ord("!"), 3 | (3 << 8)),)
    assert comp.pattern_keys[1] == ((ELEM_PUNCT_RUN, ord("?"), 2 | (5 << 8)),)


def test_punct_run_of_one_degrades_to_punct(tmp_path: Path) -> None:
    comp = compile_lines(["гвоздь !(1)"], tmp_path)
    (key,) = comp.pattern_keys
    assert key[1] == (ELEM_PUNCT, ord("!"), 0)


def test_escaped_parens_with_wide_gap(tmp_path: Path) -> None:
    comp = compile_lines([r"\( __ \)"], tmp_path)
    (key,) = comp.pattern_keys
    assert key == (
        (ELEM_PUNCT, ord("("), 0),
        (ELEM_ANY, 1, MAX_ANY_SPAN),
        (ELEM_PUNCT, ord(")"), 0),
    )


def test_punct_initial_pattern_in_start_section(tmp_path: Path) -> None:
    comp = compile_lines(["!(2+)"], tmp_path)
    blob = build_blob(comp)
    punct_start_off, punct_start_count = struct.unpack_from("<II", blob, 124)
    assert punct_start_count == 1
    (pid,) = struct.unpack_from("<H", blob, punct_start_off)
    assert pid == 0


def test_wide_gap_position_errors(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="cannot end with a gap"):
        compile_lines([r"\( __"], tmp_path)
    with pytest.raises(RuleError, match="cannot start with a gap"):
        compile_lines([r"__ \)"], tmp_path)
    with pytest.raises(RuleError, match="adjacent gaps"):
        compile_lines([r"\( __ _ \)"], tmp_path)


def test_punct_run_after_gap_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="cannot follow a gap"):
        compile_lines(["гвоздь _ !(2+)"], tmp_path)


def test_bad_punct_counts(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="bad punctuation count"):
        compile_lines(["!(0+)"], tmp_path)
    with pytest.raises(RuleError, match="bad punctuation count"):
        compile_lines(["!(5-2)"], tmp_path)


def test_unescaped_metachar_still_errors(tmp_path: Path) -> None:
    with pytest.raises(RuleError, match="standalone '\\*'"):
        compile_lines(["* гвоздь"], tmp_path)
    with pytest.raises(RuleError, match="escapes a standalone"):
        compile_lines([r"гво\здь"], tmp_path)
