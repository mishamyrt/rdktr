"""Text normalization (must mirror src/normalize.c exactly)."""


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


def word_variants(word: str) -> list[str]:
    """don't / don’t are different byte sequences; index both."""
    if "'" in word:
        return [word, word.replace("'", "’")]
    if "’" in word:
        return [word.replace("’", "'"), word]
    return [word]
