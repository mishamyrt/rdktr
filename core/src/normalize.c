#include "rdktr_internal.h"

/* UTF-8 encodings used below:
 *   А..П  U+0410..041F = D0 90..D0 9F   ->  а..п  D0 B0..D0 BF
 *   Р..Я  U+0420..042F = D0 A0..D0 AF   ->  р..я  D1 80..D1 8F
 *   Ё     U+0401       = D0 81          ->  е     D0 B5
 *   ё     U+0451       = D1 91          ->  е     D0 B5
 * All mappings are 2 bytes -> 2 bytes, ASCII is 1 -> 1, so normalized
 * offsets are identical to the original ones. */
void rdktr_normalize_utf8(const uint8_t *in, uint8_t *out, size_t len) {
    size_t i = 0;
    while (i < len) {
        uint8_t b = in[i];
        if (b < 0x80) {
            out[i] = (b >= 'A' && b <= 'Z') ? (uint8_t)(b + 0x20) : b;
            i++;
            continue;
        }
        if (b == 0xD0 && i + 1 < len) {
            uint8_t c = in[i + 1];
            if (c == 0x81) { /* Ё */
                out[i] = 0xD0;
                out[i + 1] = 0xB5;
            } else if (c >= 0x90 && c <= 0x9F) { /* А-П */
                out[i] = 0xD0;
                out[i + 1] = (uint8_t)(c + 0x20);
            } else if (c >= 0xA0 && c <= 0xAF) { /* Р-Я */
                out[i] = 0xD1;
                out[i + 1] = (uint8_t)(c - 0x20);
            } else {
                out[i] = b;
                out[i + 1] = c;
            }
            i += 2;
            continue;
        }
        if (b == 0xD1 && i + 1 < len && in[i + 1] == 0x91) { /* ё */
            out[i] = 0xD0;
            out[i + 1] = 0xB5;
            i += 2;
            continue;
        }
        out[i] = b;
        i++;
    }
}
