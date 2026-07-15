/* rdktr — fast stop-word / text-cleanliness checker.
 *
 * The engine matches a pre-compiled rule set (see Scripts/compile_rules.py)
 * against UTF-8 text and reports byte ranges of the original input.
 */
#ifndef RDKTR_H
#define RDKTR_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct rdktr_engine rdktr_engine;

typedef struct {
    uint32_t start;   /* byte offset into the original UTF-8 text (inclusive) */
    uint32_t end;     /* byte offset into the original UTF-8 text (exclusive) */
    uint32_t rule_id; /* 0 .. rdktr_rule_count()-1 */
} rdktr_match;

/* Creates an engine from a compiled rules blob.
 * The blob is used in place (zero copy) and must stay valid and unchanged
 * for the whole lifetime of the engine. The pointer must be 4-byte aligned.
 * Returns NULL if the blob is malformed. */
rdktr_engine *rdktr_create(const void *blob, size_t size);

/* Creates an engine from the rule set embedded at compile time. */
rdktr_engine *rdktr_create_default(void);

void rdktr_destroy(rdktr_engine *engine);

/* Checks `len` bytes of UTF-8 text.
 * Returns the total number of matches; at most `cap` of them are written
 * to `out`. Call with out == NULL, cap == 0 to count matches first.
 * Matches are sorted by start offset. Returns 0 on allocation failure. */
size_t rdktr_check(const rdktr_engine *engine, const char *utf8, size_t len,
                   rdktr_match *out, size_t cap);

uint32_t rdktr_rule_count(const rdktr_engine *engine);
/* Returned strings are UTF-8, NUL-terminated, owned by the engine/blob.
 * NULL if rule_id is out of range. */
const char *rdktr_rule_title(const rdktr_engine *engine, uint32_t rule_id);
const char *rdktr_rule_description(const rdktr_engine *engine, uint32_t rule_id);
uint32_t rdktr_rule_weight(const rdktr_engine *engine, uint32_t rule_id);

#ifdef __cplusplus
}
#endif

#endif /* RDKTR_H */
