#include <stdlib.h>
#include <string.h>

#include "rdktr.h"
#include "rdktr_internal.h"

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

/* offset/size pair fits into the blob, is 4-byte aligned */
static int section_ok(size_t blob_size, uint32_t off, uint64_t bytes) {
    if (off % 4 != 0) return 0;
    if ((uint64_t)off + bytes > blob_size) return 0;
    return 1;
}

rdktr_engine *rdktr_create(const void *blob_ptr, size_t size) {
    const uint8_t *blob = (const uint8_t *)blob_ptr;
    if (!blob || size < RDKTR_HEADER_SIZE) return NULL;
    if (((uintptr_t)blob) % 4 != 0) return NULL;
    if (memcmp(blob, "RDK1", 4) != 0) return NULL;
    if (rd32(blob + 4) != RDKTR_VERSION) return NULL;

    uint32_t total_size = rd32(blob + 8);
    if (total_size < RDKTR_HEADER_SIZE || total_size > size) return NULL;

    rdktr_engine e;
    memset(&e, 0, sizeof(e));
    e.blob = blob;
    e.blob_size = total_size;

    e.rule_count = rd32(blob + 12);
    uint32_t rules_off = rd32(blob + 16);
    uint32_t strpool_off = rd32(blob + 20);
    e.strpool_size = rd32(blob + 24);
    e.dat_size = rd32(blob + 28);
    uint32_t dat_base_off = rd32(blob + 32);
    uint32_t dat_check_off = rd32(blob + 36);
    uint32_t dat_word_id_off = rd32(blob + 40);
    uint32_t dat_prefix_id_off = rd32(blob + 44);
    e.word_count = rd32(blob + 48);
    e.prefix_count = rd32(blob + 52);
    e.pat_count = rd32(blob + 56);
    uint32_t pat_off = rd32(blob + 60);
    uint32_t pat_rules_off = rd32(blob + 64);
    e.pat_rules_count = rd32(blob + 68);
    uint32_t elems_off = rd32(blob + 72);
    e.elem_count = rd32(blob + 76);
    uint32_t word_index_off = rd32(blob + 80);
    uint32_t prefix_index_off = rd32(blob + 84);
    uint32_t start_list_off = rd32(blob + 88);
    e.start_list_count = rd32(blob + 92);
    e.max_phrase_len = rd32(blob + 96);
    e.comma_rule_id = rd32(blob + 100);
    e.comma_threshold = rd32(blob + 104);
    memcpy(e.lang, blob + 108, 4);
    e.lang[4] = '\0';

    if (!section_ok(total_size, rules_off, (uint64_t)e.rule_count * 12)) return NULL;
    if (!section_ok(total_size, strpool_off, e.strpool_size)) return NULL;
    if (e.strpool_size == 0) return NULL;
    if (blob[strpool_off + e.strpool_size - 1] != '\0') return NULL;
    if (e.dat_size == 0) return NULL;
    if (!section_ok(total_size, dat_base_off, (uint64_t)e.dat_size * 4)) return NULL;
    if (!section_ok(total_size, dat_check_off, (uint64_t)e.dat_size * 4)) return NULL;
    if (!section_ok(total_size, dat_word_id_off, (uint64_t)e.dat_size * 4)) return NULL;
    if (!section_ok(total_size, dat_prefix_id_off, (uint64_t)e.dat_size * 4)) return NULL;
    if (!section_ok(total_size, pat_off, (uint64_t)e.pat_count * 16)) return NULL;
    if (!section_ok(total_size, pat_rules_off, (uint64_t)e.pat_rules_count * 4)) return NULL;
    if (!section_ok(total_size, elems_off, (uint64_t)e.elem_count * 12)) return NULL;
    if (!section_ok(total_size, word_index_off, (uint64_t)e.word_count * 8)) return NULL;
    if (!section_ok(total_size, prefix_index_off, (uint64_t)e.prefix_count * 8)) return NULL;
    if (!section_ok(total_size, start_list_off, (uint64_t)e.start_list_count * 4)) return NULL;
    if (e.max_phrase_len == 0 || e.max_phrase_len > 1024) return NULL;
    if (e.comma_rule_id != RDKTR_NONE && e.comma_rule_id >= e.rule_count) return NULL;

    e.rules = (const rdktr_rule_entry *)(blob + rules_off);
    e.strpool = (const char *)(blob + strpool_off);
    e.dat_base = (const uint32_t *)(blob + dat_base_off);
    e.dat_check = (const uint32_t *)(blob + dat_check_off);
    e.dat_word_id = (const uint32_t *)(blob + dat_word_id_off);
    e.dat_prefix_id = (const uint32_t *)(blob + dat_prefix_id_off);
    e.pats = (const rdktr_pattern_entry *)(blob + pat_off);
    e.pat_rules = (const uint32_t *)(blob + pat_rules_off);
    e.elems = (const rdktr_elem *)(blob + elems_off);
    e.word_index = (const rdktr_start_index *)(blob + word_index_off);
    e.prefix_index = (const rdktr_start_index *)(blob + prefix_index_off);
    e.start_list = (const uint32_t *)(blob + start_list_off);

    /* cross-references */
    for (uint32_t i = 0; i < e.rule_count; i++) {
        if (e.rules[i].title_off >= e.strpool_size) return NULL;
        if (e.rules[i].desc_off >= e.strpool_size) return NULL;
    }
    for (uint32_t i = 0; i < e.pat_count; i++) {
        const rdktr_pattern_entry *p = &e.pats[i];
        if ((uint64_t)p->rules_start + p->rules_count > e.pat_rules_count) return NULL;
        if (p->elem_count == 0) return NULL;
        if ((uint64_t)p->elem_start + p->elem_count > e.elem_count) return NULL;
        /* the engine spawns partials on words/prefixes and needs a non-gap
         * final element to terminate a match */
        uint32_t first = e.elems[p->elem_start].kind;
        uint32_t last = e.elems[p->elem_start + p->elem_count - 1].kind;
        if (first != RDKTR_ELEM_WORD && first != RDKTR_ELEM_PREFIX) return NULL;
        if (last == RDKTR_ELEM_GAP) return NULL;
    }
    for (uint32_t i = 0; i < e.pat_rules_count; i++) {
        if (e.pat_rules[i] >= e.rule_count) return NULL;
    }
    for (uint32_t i = 0; i < e.elem_count; i++) {
        const rdktr_elem *el = &e.elems[i];
        switch (el->kind) {
            case RDKTR_ELEM_WORD:
                if (el->a >= e.word_count) return NULL;
                break;
            case RDKTR_ELEM_PREFIX:
                if (el->a >= e.prefix_count) return NULL;
                break;
            case RDKTR_ELEM_GAP:
                if (el->a > el->b || el->b == 0 || el->b > 64) return NULL;
                break;
            case RDKTR_ELEM_PUNCT:
                if (el->a == 0 || el->a >= 0x110000) return NULL;
                break;
            default:
                return NULL;
        }
    }
    for (uint32_t i = 0; i < e.word_count; i++) {
        if ((uint64_t)e.word_index[i].start + e.word_index[i].count >
            e.start_list_count)
            return NULL;
    }
    for (uint32_t i = 0; i < e.prefix_count; i++) {
        if ((uint64_t)e.prefix_index[i].start + e.prefix_index[i].count >
            e.start_list_count)
            return NULL;
    }
    for (uint32_t i = 0; i < e.start_list_count; i++) {
        if (e.start_list[i] >= e.pat_count) return NULL;
    }
    for (uint32_t i = 0; i < e.dat_size; i++) {
        if (e.dat_check[i] != RDKTR_NONE && e.dat_check[i] >= e.dat_size) return NULL;
        if (e.dat_word_id[i] != RDKTR_NONE && e.dat_word_id[i] >= e.word_count)
            return NULL;
        if (e.dat_prefix_id[i] != RDKTR_NONE && e.dat_prefix_id[i] >= e.prefix_count)
            return NULL;
    }

    rdktr_engine *out = (rdktr_engine *)malloc(sizeof(rdktr_engine));
    if (!out) return NULL;
    *out = e;
    return out;
}

rdktr_engine *rdktr_create_embedded(const char *lang) {
    if (!lang) return NULL;
    for (size_t i = 0; i < rdktr_embedded_ruleset_count; i++) {
        const rdktr_embedded_ruleset *r = &rdktr_embedded_rulesets[i];
        if (strcmp(r->lang, lang) == 0) return rdktr_create(r->data, r->size);
    }
    return NULL;
}

size_t rdktr_embedded_count(void) { return rdktr_embedded_ruleset_count; }

const char *rdktr_embedded_lang(size_t index) {
    if (index >= rdktr_embedded_ruleset_count) return NULL;
    return rdktr_embedded_rulesets[index].lang;
}

void rdktr_destroy(rdktr_engine *engine) { free(engine); }

const char *rdktr_lang(const rdktr_engine *engine) {
    return engine ? engine->lang : NULL;
}

uint32_t rdktr_rule_count(const rdktr_engine *engine) {
    return engine ? engine->rule_count : 0;
}

const char *rdktr_rule_title(const rdktr_engine *engine, uint32_t rule_id) {
    if (!engine || rule_id >= engine->rule_count) return NULL;
    return engine->strpool + engine->rules[rule_id].title_off;
}

const char *rdktr_rule_description(const rdktr_engine *engine, uint32_t rule_id) {
    if (!engine || rule_id >= engine->rule_count) return NULL;
    return engine->strpool + engine->rules[rule_id].desc_off;
}

uint32_t rdktr_rule_weight(const rdktr_engine *engine, uint32_t rule_id) {
    if (!engine || rule_id >= engine->rule_count) return 0;
    return engine->rules[rule_id].weight;
}
