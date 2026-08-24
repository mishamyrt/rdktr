#include "rdktr_internal.h"

/* Case folding for the two-byte UTF-8 range (U+0080..U+07FF), which covers
 * every letter is_word_core() accepts outside ASCII except Latin Extended-B
 * (U+0180..U+024F, whose case pairs are too irregular to fold by arithmetic).
 *
 * Every mapping below stays inside U+0080..U+07FF, so a two-byte sequence
 * always folds to another two-byte sequence and normalized offsets remain
 * identical to the original ones. Mirror of _fold() in scripts/
 * rules_compiler/normalize.py — the two must agree exactly. */
static uint32_t fold_cp2(uint32_t cp) {
    /* Cyrillic: А-Я -> а-я, Ё/ё -> е */
    if (cp >= 0x410 && cp <= 0x42F) return cp + 0x20;
    if (cp == 0x401 || cp == 0x451) return 0x435;
    /* Latin-1 Supplement: À-Þ -> à-þ (× at U+00D7 is not a letter) */
    if (cp >= 0xC0 && cp <= 0xDE && cp != 0xD7) return cp + 0x20;
    /* Latin Extended-A: even/odd upper/lower pairs, with three exceptions */
    if (cp >= 0x100 && cp <= 0x137) return (cp & 1) ? cp : cp + 1;
    if (cp >= 0x139 && cp <= 0x148) return (cp & 1) ? cp + 1 : cp;
    if (cp >= 0x14A && cp <= 0x177) return (cp & 1) ? cp : cp + 1;
    if (cp == 0x178) return 0xFF; /* Ÿ -> ÿ */
    if (cp >= 0x179 && cp <= 0x17E) return (cp & 1) ? cp + 1 : cp;
    return cp;
}

/* Case-folds ASCII, Latin-1, Latin Extended-A and Cyrillic in place-sized
 * fashion: every replacement keeps the UTF-8 byte length, so `out` offsets
 * match `in` offsets 1:1. Bytes that are not part of a well-formed two-byte
 * sequence are copied through untouched. */
void rdktr_normalize_utf8(const uint8_t *in, uint8_t *out, size_t len) {
    size_t i = 0;
    while (i < len) {
        uint8_t b = in[i];
        if (b < 0x80) {
            out[i] = (b >= 'A' && b <= 'Z') ? (uint8_t)(b + 0x20) : b;
            i++;
            continue;
        }
        if (b >= 0xC2 && b <= 0xDF && i + 1 < len && (in[i + 1] & 0xC0) == 0x80) {
            uint32_t cp = ((uint32_t)(b & 0x1F) << 6) | (uint32_t)(in[i + 1] & 0x3F);
            uint32_t f = fold_cp2(cp);
            out[i] = (uint8_t)(0xC0 | (f >> 6));
            out[i + 1] = (uint8_t)(0x80 | (f & 0x3F));
            i += 2;
            continue;
        }
        out[i] = b;
        i++;
    }
}
