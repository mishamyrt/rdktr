#ifndef RDKTR_INTERNAL_H
#define RDKTR_INTERNAL_H

#include <stddef.h>
#include <stdint.h>

#define RDKTR_NONE 0xFFFFFFFFu

/* Blob layout: fixed 100-byte header followed by 4-byte aligned sections.
 * All integers are little-endian u32. Produced by Scripts/compile_rules.py. */
#define RDKTR_HEADER_SIZE 100
#define RDKTR_VERSION 1

typedef struct {
    uint32_t title_off; /* into string pool */
    uint32_t desc_off;  /* into string pool */
    uint32_t weight;
} rdktr_rule_entry;

typedef struct {
    uint32_t rules_start; /* into pat_rules array */
    uint32_t rules_count;
} rdktr_pattern_entry;

typedef struct {
    uint32_t trans_start; /* into ac_trans array */
    uint32_t trans_count;
    uint32_t fail;
    uint32_t out_start; /* into ac_out array */
    uint32_t out_count;
} rdktr_ac_state;

typedef struct {
    uint32_t word_id;
    uint32_t next;
} rdktr_ac_trans;

typedef struct {
    uint32_t pattern_id;
    uint32_t tok_len; /* pattern length in words */
} rdktr_ac_out;

struct rdktr_engine {
    const uint8_t *blob;
    size_t blob_size;

    uint32_t rule_count;
    const rdktr_rule_entry *rules;
    const char *strpool;
    uint32_t strpool_size;

    /* word dictionary: double-array trie over normalized UTF-8 bytes */
    uint32_t dat_size;
    const uint32_t *dat_base;
    const uint32_t *dat_check;
    const uint32_t *dat_word_id;    /* exact-word terminal -> word id */
    const uint32_t *dat_prefix_pat; /* prefix terminal -> pattern id */

    uint32_t pat_count;
    const rdktr_pattern_entry *pats;
    const uint32_t *pat_rules;
    uint32_t pat_rules_count;

    /* phrase automaton (Aho-Corasick over word ids) */
    uint32_t ac_state_count;
    const rdktr_ac_state *ac_states;
    const rdktr_ac_trans *ac_trans;
    uint32_t ac_trans_count;
    const rdktr_ac_out *ac_out;
    uint32_t ac_out_count;

    uint32_t max_phrase_len;
    uint32_t comma_rule_id; /* RDKTR_NONE when disabled */
    uint32_t comma_threshold;
};

/* normalize.c: case-fold ASCII and Cyrillic, fold ё -> е. Every replacement
 * keeps the UTF-8 byte length, so `out` offsets match `in` offsets 1:1. */
void rdktr_normalize_utf8(const uint8_t *in, uint8_t *out, size_t len);

#endif /* RDKTR_INTERNAL_H */
