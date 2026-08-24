"""Text normalization (must mirror src/normalize.c exactly)."""


def _fold(o: int) -> int:
    """Mirror of fold_cp2() in src/normalize.c, plus ASCII.

    Every mapping keeps the UTF-8 byte length (ASCII stays 1 byte, everything
    else stays inside U+0080..U+07FF), so normalized offsets are identical to
    the original ones. Latin Extended-B (U+0180..U+024F) is deliberately not
    folded: its case pairs are too irregular to express as arithmetic, and
    both sides must agree exactly.
    """
    if 0x41 <= o <= 0x5A:  # A-Z
        return o + 0x20
    if 0x410 <= o <= 0x42F:  # А-Я
        return o + 0x20
    if o in (0x401, 0x451):  # Ё, ё
        return 0x435
    if 0xC0 <= o <= 0xDE and o != 0xD7:  # À-Þ (× is not a letter)
        return o + 0x20
    if 0x100 <= o <= 0x137:  # Latin Extended-A: even upper / odd lower
        return o if o & 1 else o + 1
    if 0x139 <= o <= 0x148:  # odd upper / even lower
        return o + 1 if o & 1 else o
    if 0x14A <= o <= 0x177:  # even upper / odd lower
        return o if o & 1 else o + 1
    if o == 0x178:  # Ÿ -> ÿ
        return 0xFF
    if 0x179 <= o <= 0x17E:  # odd upper / even lower
        return o + 1 if o & 1 else o
    return o


def normalize(s: str) -> str:
    return "".join(chr(_fold(ord(ch))) for ch in s)


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


def word_variants(word: str) -> list[str]:
    """don't / don’t are different byte sequences; index both."""
    if "'" in word:
        return [word, word.replace("'", "’")]
    if "’" in word:
        return [word.replace("’", "'"), word]
    return [word]
