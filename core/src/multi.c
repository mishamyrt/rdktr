#include <stdlib.h>
#include <string.h>

#include "rdktr.h"
#include "rdktr_internal.h"

/* Multi-language checking. The text is split into paragraphs (blocks
 * separated by blank lines; a single '\n' is a soft break inside a
 * paragraph, so phrases survive line wrapping). Each paragraph is checked
 * by exactly one engine — chosen by the script (Cyrillic vs Latin) that
 * dominates the paragraph, falling back to the dominant script of the
 * whole document when the paragraph is ambiguous; when the document ties
 * too, every engine runs and the results are merged.
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
        /* Dispatch is by script, so two rule sets sharing one script are
         * indistinguishable and the second would silently never be used.
         * Reject that here instead of shipping a dead rule set. */
        for (size_t k = 0; k < i; k++) {
            if (m->script[k] == m->script[i]) {
                rdktr_multi_destroy(m);
                return NULL;
            }
        }
    }
    return m;
}

rdktr_multi *rdktr_multi_create_default(void) {
    size_t n = rdktr_embedded_ruleset_count;
    if (n == 0) return NULL;
    const void **blobs = (const void **)calloc(n, sizeof(*blobs));
    size_t *sizes = (size_t *)calloc(n, sizeof(*sizes));
    if (!blobs || !sizes) {
        free(blobs);
        free(sizes);
        return NULL;
    }
    for (size_t i = 0; i < n; i++) {
        blobs[i] = rdktr_embedded_rulesets[i].data;
        sizes[i] = rdktr_embedded_rulesets[i].size;
    }
    rdktr_multi *m = rdktr_multi_create(blobs, sizes, n);
    free(blobs);
    free(sizes);
    return m;
}

void rdktr_multi_destroy(rdktr_multi *m) {
    if (!m) return;
    for (size_t i = 0; i < m->count; i++) rdktr_destroy(m->engines[i]);
    free(m->engines);
    free(m->rule_base);
    free(m->script);
    free(m);
}

/* Sort key for merged results: by start, longer span first, then rule id —
 * the ordering rdktr_check promises callers. */
static int match_pos_cmp(const void *pa, const void *pb) {
    const rdktr_match *a = (const rdktr_match *)pa, *b = (const rdktr_match *)pb;
    if (a->start != b->start) return a->start < b->start ? -1 : 1;
    if (a->end != b->end) return a->end > b->end ? -1 : 1;
    if (a->rule_id != b->rule_id) return a->rule_id < b->rule_id ? -1 : 1;
    return 0;
}

size_t rdktr_multi_check(const rdktr_multi *m, const char *utf8, size_t len,
                         rdktr_match *out, size_t cap) {
    if (!m || (!utf8 && len > 0)) return 0;
    const uint8_t *text = (const uint8_t *)utf8;

    size_t doc_cyr = 0, doc_lat = 0;
    count_scripts(text, len, &doc_cyr, &doc_lat);
    int doc_script = dominant_script(doc_cyr, doc_lat);

    /* per-paragraph scratch, grown on demand and reused across paragraphs */
    rdktr_match *buf = NULL;
    size_t buf_cap = 0;

    size_t total = 0;
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
        /* Still ambiguous — an exact tie both in the paragraph and in the
         * whole document. Any single pick would be a coin flip that leaves
         * half the text effectively unchecked, so run every engine and merge.
         * Scripts are unique per engine (see rdktr_multi_create), so the
         * unambiguous case below selects exactly one. */

        size_t n_para = 0;
        for (size_t ei = 0; ei < m->count; ei++) {
            if (script != SCRIPT_NONE && m->script[ei] != script) continue;

            rdktr_match *matches;
            size_t n = rdktr_check_alloc(m->engines[ei], utf8 + p, q - p, &matches);
            /* Same contract as rdktr_check: a partial count would be
             * indistinguishable from a real result, so report nothing. */
            if (n == SIZE_MAX) {
                free(buf);
                return 0;
            }
            if (n == 0) continue;
            if (n_para + n > buf_cap) {
                size_t want = buf_cap ? buf_cap * 2 : 64;
                while (want < n_para + n) want *= 2;
                rdktr_match *grown =
                    (rdktr_match *)realloc(buf, want * sizeof(*grown));
                if (!grown) {
                    free(matches);
                    free(buf);
                    return 0;
                }
                buf = grown;
                buf_cap = want;
            }
            for (size_t k = 0; k < n; k++) {
                buf[n_para].start = matches[k].start + (uint32_t)p;
                buf[n_para].end = matches[k].end + (uint32_t)p;
                buf[n_para].rule_id = matches[k].rule_id + m->rule_base[ei];
                n_para++;
            }
            free(matches);
        }
        /* each engine returns sorted matches; merging two breaks the order */
        if (script == SCRIPT_NONE && n_para > 1)
            qsort(buf, n_para, sizeof(*buf), match_pos_cmp);

        for (size_t k = 0; k < n_para; k++) {
            if (out && total < cap) out[total] = buf[k];
            total++;
        }
        p = q + 1;
    }
    free(buf);
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
