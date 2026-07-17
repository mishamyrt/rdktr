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

static int is_connector(uint32_t cp) {
    return cp == '-' || cp == '\'' || cp == 0x2019 /* ’ */;
}

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

/* ---- pattern matching --------------------------------------------------------
 * Patterns are element sequences (word / prefix / gap / punctuation). The
 * scanner keeps a small set of partial matches and advances each one on
 * every token or punctuation codepoint. Partials spawn when a token matches
 * the first element of a pattern (found via the word/prefix start index). */

typedef struct {
    uint32_t pat;   /* pattern id */
    uint32_t elem;  /* index of the next element to match (within pattern) */
    uint32_t gap;   /* words consumed by the gap at `elem`, if it is one */
    uint32_t start; /* byte offset of the first matched token */
} rdktr_partial;

/* Enough for real texts: a partial lives at most max_phrase_len tokens and
 * only spawns when a pattern's first word occurs. Overflow drops spawns. */
#define RDKTR_MAX_PARTIALS 128

typedef struct {
    rdktr_partial v[RDKTR_MAX_PARTIALS];
    uint32_t n;
} partial_set;

static void partial_push(partial_set *s, uint32_t pat, uint32_t elem,
                         uint32_t gap, uint32_t start) {
    if (s->n < RDKTR_MAX_PARTIALS) {
        s->v[s->n].pat = pat;
        s->v[s->n].elem = elem;
        s->v[s->n].gap = gap;
        s->v[s->n].start = start;
        s->n++;
    }
}

static void emit_pattern(const rdktr_engine *e, match_vec *out, uint32_t pattern_id,
                         uint32_t start, uint32_t end) {
    const rdktr_pattern_entry *p = &e->pats[pattern_id];
    for (uint32_t i = 0; i < p->rules_count; i++)
        vec_push(out, start, end, e->pat_rules[p->rules_start + i]);
}

static int prefix_hit(const uint32_t *hits, int n, uint32_t prefix_id) {
    for (int i = 0; i < n; i++)
        if (hits[i] == prefix_id) return 1;
    return 0;
}

/* Is word_id a member of the lexeme set? Sets are sorted ascending. */
static int lexeme_has_word(const rdktr_engine *e, uint32_t lexeme_id,
                           uint32_t word_id) {
    const rdktr_start_index *lx = &e->lexeme_index[lexeme_id];
    uint32_t lo = 0, hi = lx->count;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        uint32_t w = e->lexeme_words[lx->start + mid];
        if (w == word_id) return 1;
        if (w < word_id)
            lo = mid + 1;
        else
            hi = mid;
    }
    return 0;
}

/* Does a word/prefix/lexeme element accept the current token? */
static int elem_takes_token(const rdktr_engine *e, const rdktr_elem *el,
                            uint32_t word_id, const uint32_t *hits, int n_hits) {
    if (el->kind == RDKTR_ELEM_WORD)
        return word_id != RDKTR_NONE16 && el->a == word_id;
    if (el->kind == RDKTR_ELEM_PREFIX) return prefix_hit(hits, n_hits, el->a);
    if (el->kind == RDKTR_ELEM_LEXEME)
        return word_id != RDKTR_NONE16 && lexeme_has_word(e, el->a, word_id);
    return 0;
}

/* Move a partial past element `next_idx` (already matched). Emits the match
 * when the pattern is complete, otherwise keeps the partial alive. */
static void partial_advance(const rdktr_engine *e, partial_set *out_set,
                            match_vec *out, const rdktr_partial *p,
                            uint32_t next_idx, uint32_t end) {
    const rdktr_pattern_entry *pat = &e->pats[p->pat];
    if (next_idx == pat->elem_count)
        emit_pattern(e, out, p->pat, p->start, end);
    else
        partial_push(out_set, p->pat, next_idx, 0, p->start);
}

/* Advance every partial with the token [tok_start, tok_end). */
static void partials_on_token(const rdktr_engine *e, partial_set *set,
                              match_vec *out, uint32_t word_id,
                              const uint32_t *hits, int n_hits,
                              uint32_t tok_start, uint32_t tok_end) {
    partial_set next;
    next.n = 0;

    for (uint32_t i = 0; i < set->n; i++) {
        const rdktr_partial *p = &set->v[i];
        const rdktr_pattern_entry *pat = &e->pats[p->pat];
        const rdktr_elem *el = &e->elems[pat->elem_start + p->elem];
        if (el->kind == RDKTR_ELEM_GAP) {
            /* gap satisfied: the element after it may take this token
             * (a gap is never the last element) */
            if (p->gap >= el->a &&
                elem_takes_token(e, el + 1, word_id, hits, n_hits))
                partial_advance(e, &next, out, p, p->elem + 2, tok_end);
            /* the token may extend the gap */
            if (p->gap + 1 <= el->b)
                partial_push(&next, p->pat, p->elem, p->gap + 1, p->start);
        } else if (el->kind == RDKTR_ELEM_ANY) {
            /* lazy: the follower wins over extending (never the last elem) */
            if (p->gap >= el->a &&
                elem_takes_token(e, el + 1, word_id, hits, n_hits))
                partial_advance(e, &next, out, p, p->elem + 2, tok_end);
            else if (p->gap + 1 <= el->b)
                partial_push(&next, p->pat, p->elem, p->gap + 1, p->start);
        } else if (elem_takes_token(e, el, word_id, hits, n_hits)) {
            partial_advance(e, &next, out, p, p->elem + 1, tok_end);
        }
        /* expected punctuation or a mismatch: the partial dies */
    }

    /* spawn partials whose first element matches this token */
    if (word_id != RDKTR_NONE16) {
        const rdktr_start_index *si = &e->word_index[word_id];
        for (uint32_t k = 0; k < si->count; k++) {
            uint32_t pid = e->start_list[si->start + k];
            rdktr_partial fresh = {pid, 0, 0, tok_start};
            partial_advance(e, &next, out, &fresh, 1, tok_end);
        }
    }
    for (int h = 0; h < n_hits; h++) {
        const rdktr_start_index *si = &e->prefix_index[hits[h]];
        for (uint32_t k = 0; k < si->count; k++) {
            uint32_t pid = e->start_list[si->start + k];
            rdktr_partial fresh = {pid, 0, 0, tok_start};
            partial_advance(e, &next, out, &fresh, 1, tok_end);
        }
    }

    *set = next;
}

/* One matched punctuation char of a run: emit/advance when the count is in
 * range, stay in the run while below the max. `elem` is the run's index in
 * the pattern, `count` the chars matched so far including this one. */
static void punct_run_step(const rdktr_engine *e, partial_set *next,
                           match_vec *out, const rdktr_partial *p,
                           uint32_t elem, uint32_t count, uint32_t end) {
    const rdktr_pattern_entry *pat = &e->pats[p->pat];
    const rdktr_elem *el = &e->elems[pat->elem_start + elem];
    uint32_t mn = el->b & 0xFF, mx = el->b >> 8; /* mx 0 = unbounded */
    if (count >= mn && (mx == 0 || count <= mx))
        partial_advance(e, next, out, p, elem + 1, end);
    if (mx == 0 || count < mx)
        partial_push(next, p->pat, elem, count, p->start);
}

/* Advance partials over a punctuation codepoint [start, end). Partials that
 * do not expect this punctuation die (punctuation breaks phrases), except
 * `__` which swallows anything up to its follower. */
static void partials_on_punct(const rdktr_engine *e, partial_set *set,
                              match_vec *out, uint32_t cp, uint32_t start,
                              uint32_t end) {
    partial_set next;
    next.n = 0;

    for (uint32_t i = 0; i < set->n; i++) {
        const rdktr_partial *p = &set->v[i];
        const rdktr_pattern_entry *pat = &e->pats[p->pat];
        const rdktr_elem *el = &e->elems[pat->elem_start + p->elem];
        if (el->kind == RDKTR_ELEM_PUNCT && el->a == cp) {
            partial_advance(e, &next, out, p, p->elem + 1, end);
        } else if (el->kind == RDKTR_ELEM_PUNCT_RUN && el->a == cp) {
            punct_run_step(e, &next, out, p, p->elem, p->gap + 1, end);
        } else if (el->kind == RDKTR_ELEM_GAP && p->gap >= el->a &&
                   el[1].kind == RDKTR_ELEM_PUNCT && el[1].a == cp) {
            partial_advance(e, &next, out, p, p->elem + 2, end);
        } else if (el->kind == RDKTR_ELEM_ANY) {
            /* lazy: a matching follower closes `__`, else the char extends it */
            if (p->gap >= el->a && el[1].kind == RDKTR_ELEM_PUNCT &&
                el[1].a == cp)
                partial_advance(e, &next, out, p, p->elem + 2, end);
            else if (p->gap + 1 <= el->b)
                partial_push(&next, p->pat, p->elem, p->gap + 1, p->start);
        }
    }

    /* spawn partials whose first element matches this punctuation char */
    for (uint32_t k = 0; k < e->punct_start_count; k++) {
        uint32_t pid = e->punct_start[k];
        const rdktr_elem *el = &e->elems[e->pats[pid].elem_start];
        if (el->a != cp) continue;
        rdktr_partial fresh = {pid, 0, 0, start};
        if (el->kind == RDKTR_ELEM_PUNCT)
            partial_advance(e, &next, out, &fresh, 1, end);
        else /* RDKTR_ELEM_PUNCT_RUN */
            punct_run_step(e, &next, out, &fresh, 0, 1, end);
    }

    *set = next;
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

size_t rdktr_check_alloc(const rdktr_engine *e, const char *utf8, size_t len,
                         rdktr_match **out_matches) {
    *out_matches = NULL;
    if (!e || (!utf8 && len > 0)) return 0;

    match_vec words = {0};  /* word/phrase matches (filtered for containment) */
    match_vec extra = {0};  /* structural matches (comma rule) */
    uint8_t *norm = NULL;

    if (len > 0) {
        norm = (uint8_t *)malloc(len);
        if (!norm) return SIZE_MAX;
        rdktr_normalize_utf8((const uint8_t *)utf8, norm, len);
    }

    partial_set parts;
    parts.n = 0;

    /* comma rule state */
    uint32_t commas = 0;
    size_t sent_start = 0;
    int sent_has_text = 0;

    size_t i = 0;
    while (i < len) {
        uint32_t cp;
        size_t cplen = decode_cp(norm, i, len, &cp);

        if (!is_word_core(cp)) {
            if (!is_space_cp(cp))
                partials_on_punct(e, &parts, &words, cp, (uint32_t)i,
                                  (uint32_t)(i + cplen));
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
        size_t prefix_hit_end[8];
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
                if (alive && e->dat_prefix_id[dat] != RDKTR_NONE16 &&
                    n_prefix < (int)(sizeof(prefix_hits) / sizeof(prefix_hits[0]))) {
                    prefix_hits[n_prefix] = e->dat_prefix_id[dat];
                    prefix_hit_end[n_prefix] = i + cplen;
                    n_prefix++;
                }
            }
            i += cplen;
        }
        size_t tok_end = i;

        /* a prefix needs at least one letter after the stem; a hit that
         * consumed the whole token is the stem itself, not a prefix match */
        if (n_prefix > 0 && prefix_hit_end[n_prefix - 1] == tok_end) n_prefix--;

        uint32_t word_id = alive ? e->dat_word_id[dat] : RDKTR_NONE16;

        partials_on_token(e, &parts, &words, word_id, prefix_hits, n_prefix,
                          (uint32_t)tok_start, (uint32_t)tok_end);
    }

    /* flush the last sentence for the comma rule */
    if (e->comma_rule_id != RDKTR_NONE && sent_has_text &&
        e->comma_threshold > 0 && commas >= e->comma_threshold)
        vec_push(&extra, (uint32_t)sent_start, (uint32_t)len, e->comma_rule_id);

    free(norm);

    if (words.oom || extra.oom) {
        free(words.v);
        free(extra.v);
        return SIZE_MAX;
    }

    words.n = filter_contained(words.v, words.n);

    /* merge structural matches back and restore global ordering */
    for (size_t k = 0; k < extra.n; k++)
        vec_push(&words, extra.v[k].start, extra.v[k].end, extra.v[k].rule_id);
    free(extra.v);
    if (words.oom) {
        free(words.v);
        return SIZE_MAX;
    }
    if (extra.n > 0) qsort(words.v, words.n, sizeof(rdktr_match), match_cmp);

    *out_matches = words.v;
    return words.n;
}

size_t rdktr_check(const rdktr_engine *e, const char *utf8, size_t len,
                   rdktr_match *out, size_t cap) {
    rdktr_match *matches;
    size_t n = rdktr_check_alloc(e, utf8, len, &matches);
    if (n == SIZE_MAX) return 0;
    if (out && cap > 0 && n > 0) {
        size_t w = n < cap ? n : cap;
        memcpy(out, matches, w * sizeof(rdktr_match));
    }
    free(matches);
    return n;
}
