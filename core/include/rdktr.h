/* rdktr — fast stop-word / text-cleanliness checker.
 *
 * The engine matches a pre-compiled rule set (see tools/compile_rules.py)
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

/* Creates an engine for one of the rule sets embedded at compile time
 * (e.g. "ru", "en"). Returns NULL if the language is not embedded. */
rdktr_engine *rdktr_create_embedded(const char *lang);

/* Enumerate the embedded rule sets. */
size_t rdktr_embedded_count(void);
const char *rdktr_embedded_lang(size_t index); /* NULL if out of range */

void rdktr_destroy(rdktr_engine *engine);

/* Language code of the engine's rule set, e.g. "ru". */
const char *rdktr_lang(const rdktr_engine *engine);

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

/* ---- multi-language checking with automatic language detection ---------- */

typedef struct rdktr_multi rdktr_multi;

/* Combines several single-language engines. The text is split into
 * paragraphs (by '\n'); each paragraph is checked by exactly one engine —
 * the one whose script (Cyrillic/Latin) dominates the paragraph. Paragraphs
 * without a clear winner fall back to the dominant script of the whole
 * document; when that ties too, every engine checks the paragraph and the
 * results are merged. Rule ids in matches are global: engines are numbered
 * in creation order and each engine's rules follow the previous engine's
 * rules.
 * Because dispatch is by script, no two blobs may share one script (two
 * Latin rule sets, say): such a set would never be selected, so the call
 * returns NULL instead. Also returns NULL if any blob is malformed. */
rdktr_multi *rdktr_multi_create(const void *const *blobs, const size_t *sizes,
                                size_t count);

/* All embedded rule sets (see rdktr_embedded_count). */
rdktr_multi *rdktr_multi_create_default(void);

void rdktr_multi_destroy(rdktr_multi *multi);

/* Same contract as rdktr_check, with global rule ids. */
size_t rdktr_multi_check(const rdktr_multi *multi, const char *utf8, size_t len,
                         rdktr_match *out, size_t cap);

uint32_t rdktr_multi_rule_count(const rdktr_multi *multi);
const char *rdktr_multi_rule_title(const rdktr_multi *multi, uint32_t rule_id);
const char *rdktr_multi_rule_description(const rdktr_multi *multi, uint32_t rule_id);
uint32_t rdktr_multi_rule_weight(const rdktr_multi *multi, uint32_t rule_id);
/* Language of the rule's rule set, e.g. "en". */
const char *rdktr_multi_rule_lang(const rdktr_multi *multi, uint32_t rule_id);

#ifdef __cplusplus
}
#endif

#endif /* RDKTR_H */
