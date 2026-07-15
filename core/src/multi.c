#include <stdlib.h>
#include <string.h>

#include "rdktr.h"
#include "rdktr_internal.h"

/* Multi-language checking. The text is split into paragraphs (blocks
 * separated by blank lines; a single '\n' is a soft break inside a
 * paragraph, so phrases survive line wrapping). Each paragraph is checked
 * by exactly one engine — chosen by the script (Cyrillic vs Latin) that
 * dominates the paragraph, falling back to the dominant script of the
 * whole document when the paragraph is ambiguous.
 * See logic.md: language is detected per paragraph with hysteresis. */

enum { SCRIPT_NONE = 0, SCRIPT_CYRILLIC, SCRIPT_LATIN };

struct rdktr_multi {
    size_t count;
    rdktr_engine **engines;
    uint32_t *rule_base; /* count + 1 prefix sums of rule counts */
    int *script;         /* script served by each engine */
};

static int lang_script(const char *lang) {
    static const char *const cyr[] = {"ru", "uk", "be", "bg", "sr", "mk", "kk"};
    for (size_t i = 0; i < sizeof(cyr) / sizeof(cyr[0]); i++)
        if (strcmp(lang, cyr[i]) == 0) return SCRIPT_CYRILLIC;
    return SCRIPT_LATIN;
}

/* Byte-level script counting: every Cyrillic codepoint U+0400..U+047F has
 * lead byte 0xD0/0xD1; Latin letters are ASCII or have lead byte 0xC3
 * (Latin-1 letters) / 0xC4-0xC5 (Latin Extended-A). Counting lead bytes
 * counts each character exactly once. */
static void count_scripts(const uint8_t *p, size_t n, size_t *cyr, size_t *lat) {
    for (size_t i = 0; i < n; i++) {
        uint8_t b = p[i];
        if (b < 0x80) {
            if ((b >= 'a' && b <= 'z') || (b >= 'A' && b <= 'Z')) (*lat)++;
        } else if (b == 0xD0 || b == 0xD1) {
            (*cyr)++;
        } else if (b == 0xC3 || b == 0xC4 || b == 0xC5) {
            (*lat)++;
        }
    }
}

static int dominant_script(size_t cyr, size_t lat) {
    if (cyr > lat) return SCRIPT_CYRILLIC;
    if (lat > cyr) return SCRIPT_LATIN;
    return SCRIPT_NONE;
}

rdktr_multi *rdktr_multi_create(const void *const *blobs, const size_t *sizes,
                                size_t count) {
    if (!blobs || !sizes || count == 0) return NULL;
    rdktr_multi *m = (rdktr_multi *)calloc(1, sizeof(*m));
    if (!m) return NULL;
    m->engines = (rdktr_engine **)calloc(count, sizeof(*m->engines));
    m->rule_base = (uint32_t *)calloc(count + 1, sizeof(*m->rule_base));
    m->script = (int *)calloc(count, sizeof(*m->script));
    if (!m->engines || !m->rule_base || !m->script) {
        rdktr_multi_destroy(m);
        return NULL;
    }
    for (size_t i = 0; i < count; i++) {
        rdktr_engine *e = rdktr_create(blobs[i], sizes[i]);
        if (!e) {
            rdktr_multi_destroy(m);
            return NULL;
        }
        m->engines[i] = e;
        m->count = i + 1;
        m->rule_base[i + 1] = m->rule_base[i] + rdktr_rule_count(e);
        m->script[i] = lang_script(rdktr_lang(e));
    }
    return m;
}

rdktr_multi *rdktr_multi_create_default(void) {
    const void *blobs[16];
    size_t sizes[16];
    size_t n = rdktr_embedded_ruleset_count;
    if (n > 16) n = 16;
    for (size_t i = 0; i < n; i++) {
        blobs[i] = rdktr_embedded_rulesets[i].data;
        sizes[i] = rdktr_embedded_rulesets[i].size;
    }
    return rdktr_multi_create(blobs, sizes, n);
}

void rdktr_multi_destroy(rdktr_multi *m) {
    if (!m) return;
    for (size_t i = 0; i < m->count; i++) rdktr_destroy(m->engines[i]);
    free(m->engines);
    free(m->rule_base);
    free(m->script);
    free(m);
}

static const rdktr_engine *engine_for_script(const rdktr_multi *m, int script,
                                             uint32_t *base) {
    if (script == SCRIPT_NONE) return NULL;
    for (size_t i = 0; i < m->count; i++) {
        if (m->script[i] == script) {
            *base = m->rule_base[i];
            return m->engines[i];
        }
    }
    return NULL;
}

size_t rdktr_multi_check(const rdktr_multi *m, const char *utf8, size_t len,
                         rdktr_match *out, size_t cap) {
    if (!m || (!utf8 && len > 0)) return 0;
    const uint8_t *text = (const uint8_t *)utf8;

    size_t doc_cyr = 0, doc_lat = 0;
    count_scripts(text, len, &doc_cyr, &doc_lat);
    int doc_script = dominant_script(doc_cyr, doc_lat);

    size_t total = 0;
    int overflowed = 0;
    size_t p = 0;
    while (p < len) {
        /* paragraph ends at a blank line (newline, optional spaces, newline) */
        size_t q = p;
        while (q < len) {
            if (text[q] == '\n') {
                size_t r = q + 1;
                while (r < len &&
                       (text[r] == ' ' || text[r] == '\t' || text[r] == '\r'))
                    r++;
                if (r >= len || text[r] == '\n') break;
            }
            q++;
        }

        size_t cyr = 0, lat = 0;
        count_scripts(text + p, q - p, &cyr, &lat);
        int script = dominant_script(cyr, lat);
        if (script == SCRIPT_NONE) script = doc_script;

        uint32_t base = 0;
        const rdktr_engine *e = engine_for_script(m, script, &base);
        if (e) {
            rdktr_match *matches;
            size_t n = rdktr_check_alloc(e, utf8 + p, q - p, &matches);
            if (n == SIZE_MAX) {
                overflowed = 1; /* allocation failure: report what we have */
            } else {
                for (size_t k = 0; k < n; k++) {
                    if (out && total < cap) {
                        out[total].start = matches[k].start + (uint32_t)p;
                        out[total].end = matches[k].end + (uint32_t)p;
                        out[total].rule_id = matches[k].rule_id + base;
                    }
                    total++;
                }
                free(matches);
            }
        }
        p = q + 1;
    }
    (void)overflowed;
    return total;
}

static const rdktr_engine *resolve_rule(const rdktr_multi *m, uint32_t rule_id,
                                        uint32_t *local) {
    if (!m) return NULL;
    for (size_t i = 0; i < m->count; i++) {
        if (rule_id < m->rule_base[i + 1]) {
            *local = rule_id - m->rule_base[i];
            return m->engines[i];
        }
    }
    return NULL;
}

uint32_t rdktr_multi_rule_count(const rdktr_multi *m) {
    return m ? m->rule_base[m->count] : 0;
}

const char *rdktr_multi_rule_title(const rdktr_multi *m, uint32_t rule_id) {
    uint32_t local;
    const rdktr_engine *e = resolve_rule(m, rule_id, &local);
    return e ? rdktr_rule_title(e, local) : NULL;
}

const char *rdktr_multi_rule_description(const rdktr_multi *m, uint32_t rule_id) {
    uint32_t local;
    const rdktr_engine *e = resolve_rule(m, rule_id, &local);
    return e ? rdktr_rule_description(e, local) : NULL;
}

uint32_t rdktr_multi_rule_weight(const rdktr_multi *m, uint32_t rule_id) {
    uint32_t local;
    const rdktr_engine *e = resolve_rule(m, rule_id, &local);
    return e ? rdktr_rule_weight(e, local) : 0;
}

const char *rdktr_multi_rule_lang(const rdktr_multi *m, uint32_t rule_id) {
    uint32_t local;
    const rdktr_engine *e = resolve_rule(m, rule_id, &local);
    return e ? rdktr_lang(e) : NULL;
}
