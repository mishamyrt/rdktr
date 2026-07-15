#include <stdlib.h>
#include <string.h>

#include "rdktr.h"
#include "rdktr_internal.h"

/* ---- UTF-8 ---------------------------------------------------------------- */

/* Decodes one codepoint at in[i]; returns its byte length (>= 1).
 * Invalid sequences decode as U+FFFD with length 1, which keeps the scanner
 * moving and never matches anything. */
static size_t decode_cp(const uint8_t *in, size_t i, size_t len, uint32_t *cp) {
    uint8_t b = in[i];
    if (b < 0x80) {
        *cp = b;
        return 1;
    }
    size_t need;
    uint32_t v;
    if ((b & 0xE0) == 0xC0) {
        need = 1;
        v = b & 0x1F;
    } else if ((b & 0xF0) == 0xE0) {
        need = 2;
        v = b & 0x0F;
    } else if ((b & 0xF8) == 0xF0) {
        need = 3;
        v = b & 0x07;
    } else {
        *cp = 0xFFFD;
        return 1;
    }
    if (i + need >= len) { /* not enough continuation bytes */
        *cp = 0xFFFD;
        return 1;
    }
    for (size_t k = 1; k <= need; k++) {
        uint8_t c = in[i + k];
        if ((c & 0xC0) != 0x80) {
            *cp = 0xFFFD;
            return 1;
        }
        v = (v << 6) | (c & 0x3F);
    }
    *cp = v;
    return need + 1;
}

/* ---- character classes ----------------------------------------------------- */

static int is_word_core(uint32_t cp) {
    if (cp < 0x80)
        return (cp >= 'a' && cp <= 'z') || (cp >= '0' && cp <= '9') ||
               (cp >= 'A' && cp <= 'Z');
    if (cp >= 0x400 && cp <= 0x4FF) return 1; /* Cyrillic */
    if (cp >= 0xC0 && cp <= 0x24F && cp != 0xD7 && cp != 0xF7) return 1; /* Latin ext */
    return 0;
}

static int is_connector(uint32_t cp) { return cp == '-' || cp == '\''; }

static int is_space_cp(uint32_t cp) {
    switch (cp) {
        case 0x09: case 0x0A: case 0x0B: case 0x0C: case 0x0D: case 0x20:
        case 0xA0: case 0x1680: case 0x2028: case 0x2029: case 0x202F:
        case 0x205F: case 0x3000: case 0xFEFF:
            return 1;
        default:
            return cp >= 0x2000 && cp <= 0x200A;
    }
}

static int is_sentence_end(uint32_t cp) {
    return cp == '.' || cp == '!' || cp == '?' || cp == 0x2026 /* … */ ||
           cp == '\n';
}

/* ---- match vector ----------------------------------------------------------- */

typedef struct {
    rdktr_match *v;
    size_t n, cap;
    int oom;
} match_vec;

static void vec_push(match_vec *m, uint32_t start, uint32_t end, uint32_t rule) {
    if (m->oom) return;
    if (m->n == m->cap) {
        size_t cap = m->cap ? m->cap * 2 : 64;
        rdktr_match *v = (rdktr_match *)realloc(m->v, cap * sizeof(*v));
        if (!v) {
            m->oom = 1;
            return;
        }
        m->v = v;
        m->cap = cap;
    }
    m->v[m->n].start = start;
    m->v[m->n].end = end;
    m->v[m->n].rule_id = rule;
    m->n++;
}

/* ---- automaton helpers ------------------------------------------------------ */

static uint32_t ac_next(const rdktr_engine *e, uint32_t state, uint32_t word_id) {
    for (;;) {
        const rdktr_ac_state *s = &e->ac_states[state];
        /* binary search transitions sorted by word_id */
        uint32_t lo = 0, hi = s->trans_count;
        const rdktr_ac_trans *t = e->ac_trans + s->trans_start;
        while (lo < hi) {
            uint32_t mid = (lo + hi) / 2;
            if (t[mid].word_id < word_id)
                lo = mid + 1;
            else
                hi = mid;
        }
        if (lo < s->trans_count && t[lo].word_id == word_id) return t[lo].next;
        if (state == 0) return 0;
        state = s->fail;
    }
}

static void emit_pattern(const rdktr_engine *e, match_vec *out, uint32_t pattern_id,
                         uint32_t start, uint32_t end) {
    const rdktr_pattern_entry *p = &e->pats[pattern_id];
    for (uint32_t i = 0; i < p->rules_count; i++)
        vec_push(out, start, end, e->pat_rules[p->rules_start + i]);
}

/* ---- filtering: leftmost-longest -------------------------------------------- */

static int match_cmp(const void *pa, const void *pb) {
    const rdktr_match *a = (const rdktr_match *)pa, *b = (const rdktr_match *)pb;
    if (a->start != b->start) return a->start < b->start ? -1 : 1;
    if (a->end != b->end) return a->end > b->end ? -1 : 1; /* longer first */
    if (a->rule_id != b->rule_id) return a->rule_id < b->rule_id ? -1 : 1;
    return 0;
}

/* Drops matches strictly contained inside another match; keeps different
 * rules on the same span; drops exact duplicates. Returns the new count. */
static size_t filter_contained(rdktr_match *v, size_t n) {
    if (n == 0) return 0;
    qsort(v, n, sizeof(*v), match_cmp);
    size_t kept = 0;
    uint32_t span_start = 0, span_end = 0; /* last kept span */
    uint32_t max_end = 0;
    for (size_t i = 0; i < n; i++) {
        int keep;
        if (kept == 0) {
            keep = 1;
        } else if (v[i].start == span_start && v[i].end == span_end) {
            /* same span, possibly another rule; drop exact duplicates */
            keep = !(v[kept - 1].start == v[i].start &&
                     v[kept - 1].end == v[i].end &&
                     v[kept - 1].rule_id == v[i].rule_id);
        } else {
            keep = v[i].end > max_end;
        }
        if (keep) {
            v[kept++] = v[i];
            span_start = v[i].start;
            span_end = v[i].end;
            if (v[i].end > max_end) max_end = v[i].end;
        }
    }
    return kept;
}

/* ---- main scan --------------------------------------------------------------- */

size_t rdktr_check(const rdktr_engine *e, const char *utf8, size_t len,
                   rdktr_match *out, size_t cap) {
    if (!e || (!utf8 && len > 0)) return 0;

    match_vec words = {0};  /* word/phrase matches (filtered for containment) */
    match_vec extra = {0};  /* structural matches (comma rule) */
    uint8_t *norm = NULL;
    uint32_t *ring = NULL;

    if (len > 0) {
        norm = (uint8_t *)malloc(len);
        if (!norm) return 0;
        rdktr_normalize_utf8((const uint8_t *)utf8, norm, len);
    }
    uint32_t ring_cap = e->max_phrase_len;
    ring = (uint32_t *)malloc((size_t)ring_cap * sizeof(uint32_t));
    if (!ring) {
        free(norm);
        return 0;
    }

    uint32_t ac_state = 0;
    uint32_t ring_pos = 0, ring_count = 0; /* token starts since last break */
    int break_pending = 0;                 /* punctuation seen between tokens */

    /* comma rule state */
    uint32_t commas = 0;
    size_t sent_start = 0;
    int sent_has_text = 0;

    size_t i = 0;
    while (i < len) {
        uint32_t cp;
        size_t cplen = decode_cp(norm, i, len, &cp);

        if (!is_word_core(cp)) {
            if (!is_space_cp(cp)) break_pending = 1;
            if (cp == ',') commas++;
            if (is_sentence_end(cp)) {
                if (e->comma_rule_id != RDKTR_NONE && sent_has_text &&
                    commas >= e->comma_threshold && e->comma_threshold > 0)
                    vec_push(&extra, (uint32_t)sent_start, (uint32_t)i,
                             e->comma_rule_id);
                commas = 0;
                sent_has_text = 0;
            } else if (!is_space_cp(cp) && !sent_has_text) {
                sent_start = i;
                sent_has_text = 1;
            }
            i += cplen;
            continue;
        }

        /* ---- token ---- */
        size_t tok_start = i;
        if (!sent_has_text) {
            sent_start = i;
            sent_has_text = 1;
        }
        uint32_t dat = 0;
        int alive = 1;
        uint32_t prefix_hits[8];
        int n_prefix = 0;

        while (i < len) {
            cplen = decode_cp(norm, i, len, &cp);
            int in_word;
            if (is_word_core(cp)) {
                in_word = 1;
            } else if (is_connector(cp) && i > tok_start && i + cplen < len) {
                uint32_t next_cp;
                decode_cp(norm, i + cplen, len, &next_cp);
                in_word = is_word_core(next_cp);
            } else {
                in_word = 0;
            }
            if (!in_word) break;

            if (alive) {
                for (size_t k = 0; k < cplen; k++) {
                    uint32_t t = e->dat_base[dat] + norm[i + k];
                    if (t < e->dat_size && e->dat_check[t] == dat) {
                        dat = t;
                    } else {
                        alive = 0;
                        break;
                    }
                }
                if (alive && e->dat_prefix_pat[dat] != RDKTR_NONE &&
                    n_prefix < (int)(sizeof(prefix_hits) / sizeof(prefix_hits[0])))
                    prefix_hits[n_prefix++] = e->dat_prefix_pat[dat];
            }
            i += cplen;
        }
        size_t tok_end = i;

        for (int k = 0; k < n_prefix; k++)
            emit_pattern(e, &words, prefix_hits[k], (uint32_t)tok_start,
                         (uint32_t)tok_end);

        uint32_t word_id = alive ? e->dat_word_id[dat] : RDKTR_NONE;

        if (break_pending) {
            ac_state = 0;
            ring_count = 0;
            break_pending = 0;
        }

        if (word_id == RDKTR_NONE) {
            /* unknown word: no phrase can span it */
            ac_state = 0;
            ring_count = 0;
            continue;
        }

        ring[ring_pos] = (uint32_t)tok_start;
        ring_pos = (ring_pos + 1) % ring_cap;
        if (ring_count < ring_cap) ring_count++;

        ac_state = ac_next(e, ac_state, word_id);
        const rdktr_ac_state *st = &e->ac_states[ac_state];
        for (uint32_t o = 0; o < st->out_count; o++) {
            const rdktr_ac_out *ao = &e->ac_out[st->out_start + o];
            if (ao->tok_len > ring_count) continue; /* spans a break: impossible */
            uint32_t idx = (ring_pos + ring_cap - ao->tok_len) % ring_cap;
            emit_pattern(e, &words, ao->pattern_id, ring[idx], (uint32_t)tok_end);
        }
    }

    /* flush the last sentence for the comma rule */
    if (e->comma_rule_id != RDKTR_NONE && sent_has_text &&
        e->comma_threshold > 0 && commas >= e->comma_threshold)
        vec_push(&extra, (uint32_t)sent_start, (uint32_t)len, e->comma_rule_id);

    free(ring);
    free(norm);

    if (words.oom || extra.oom) {
        free(words.v);
        free(extra.v);
        return 0;
    }

    words.n = filter_contained(words.v, words.n);

    /* merge structural matches back and restore global ordering */
    for (size_t k = 0; k < extra.n; k++)
        vec_push(&words, extra.v[k].start, extra.v[k].end, extra.v[k].rule_id);
    free(extra.v);
    if (words.oom) {
        free(words.v);
        return 0;
    }
    if (extra.n > 0) qsort(words.v, words.n, sizeof(rdktr_match), match_cmp);

    size_t n = words.n;
    if (out && cap > 0) {
        size_t w = n < cap ? n : cap;
        memcpy(out, words.v, w * sizeof(rdktr_match));
    }
    free(words.v);
    return n;
}
