/* Behavior tests for the rdktr core. No framework: cc + run.
 *   make -C core test
 * Language bindings only need thin smoke tests on top of this suite. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rdktr.h"

static int checks = 0;
static int failures = 0;
static rdktr_multi *M; /* default multi-language checker */

#define CHECK(cond, ...)                                     \
    do {                                                     \
        checks++;                                            \
        if (!(cond)) {                                       \
            failures++;                                      \
            printf("FAIL %s:%d: ", __func__, __LINE__);      \
            printf(__VA_ARGS__);                             \
            printf("\n");                                    \
        }                                                    \
    } while (0)

#define MAX_MATCHES 64

static size_t run(const char *text, rdktr_match *out) {
    return rdktr_multi_check(M, text, strlen(text), out, MAX_MATCHES);
}

/* match `idx` covers exactly `frag` and belongs to a rule titled `title` */
static void expect(const char *text, size_t idx, const char *frag,
                   const char *title, const char *func, int line) {
    rdktr_match m[MAX_MATCHES];
    size_t n = run(text, m);
    checks++;
    if (idx >= n) {
        failures++;
        printf("FAIL %s:%d: match %zu missing (got %zu) in \"%s\"\n", func,
               line, idx, n, text);
        return;
    }
    size_t frag_len = strlen(frag);
    const char *got_title = rdktr_multi_rule_title(M, m[idx].rule_id);
    if (m[idx].end - m[idx].start != frag_len ||
        memcmp(text + m[idx].start, frag, frag_len) != 0 ||
        !got_title || strcmp(got_title, title) != 0) {
        failures++;
        printf("FAIL %s:%d: want \"%s\"/%s, got \"%.*s\"/%s in \"%s\"\n", func,
               line, frag, title, (int)(m[idx].end - m[idx].start),
               text + m[idx].start, got_title ? got_title : "(null)", text);
    }
}
#define EXPECT(text, idx, frag, title) expect(text, idx, frag, title, __func__, __LINE__)

static void expect_total(const char *text, size_t want, const char *func, int line) {
    rdktr_match m[MAX_MATCHES];
    size_t n = run(text, m);
    checks++;
    if (n != want) {
        failures++;
        printf("FAIL %s:%d: want %zu matches, got %zu in \"%s\"\n", func, line,
               want, n, text);
    }
}
#define EXPECT_TOTAL(text, want) expect_total(text, want, __func__, __LINE__)

/* ---- tests ---------------------------------------------------------------- */

static void test_exact_words_and_phrases(void) {
    EXPECT_TOTAL("Это очень важно", 1);
    EXPECT("Это очень важно", 0, "очень", "Усилители");
    EXPECT("Нельзя не отметить рост", 0, "Нельзя не отметить", "Канцеляризм");
    EXPECT_TOTAL("Кошка спит на подоконнике.", 0);
}

static void test_case_and_yo_folding(void) {
    EXPECT("ОЧЕНЬ", 0, "ОЧЕНЬ", "Усилители");
    EXPECT("надежный партнер", 0, "надежный партнер", "Корпоративный штамп");
    EXPECT("надёжный партнёр", 0, "надёжный партнёр", "Корпоративный штамп");
}

static void test_phrase_gaps(void) {
    /* soft line break and repeated spaces stay inside a phrase */
    EXPECT("нельзя  не\nотметить", 0, "нельзя  не\nотметить", "Канцеляризм");
    /* punctuation breaks it */
    EXPECT_TOTAL("нельзя, не отметить", 0);
}

static void test_declensions(void) {
    EXPECT("данного", 0, "данного", "Канцеляризм");
    EXPECT("в данных обстоятельствах", 0, "данных", "Канцеляризм");
    EXPECT("существовали", 0, "существовали", "Слабый глагол");
    /* morphology expansion inside phrases */
    EXPECT("они принимали участие", 0, "принимали участие", "Газетный штамп");
    EXPECT("он примет участие", 0, "примет участие", "Газетный штамп");
}

static void test_prefixes(void) {
    EXPECT("высококвалифицированными", 0, "высококвалифицированными",
           "Необъективная оценка");
    EXPECT("we utilized the API", 0, "utilized", "Officialese");
}

static void test_word_boundaries(void) {
    EXPECT_TOTAL("выше", 0);   /* not "вы" */
    EXPECT_TOTAL("яблоня", 0); /* not "я" */
    EXPECT("я пошёл", 0, "я", "Личное местоимение");
    EXPECT_TOTAL("во-первых", 0); /* hyphenated word is one token */
}

static void test_overlaps(void) {
    EXPECT_TOTAL("ни для кого не секрет", 1);
    EXPECT("ни для кого не секрет", 0, "ни для кого не секрет",
           "Газетный штамп");
    EXPECT("это не секрет", 0, "не секрет", "Газетный штамп");
}

static void test_comma_rule(void) {
    EXPECT("раз, два, три, четыре, пять, шесть, семь.", 0,
           "раз, два, три, четыре, пять, шесть, семь",
           "Возможно, перебор с запятыми");
    EXPECT_TOTAL("раз, два и три.", 0);
}

static void test_language_detection(void) {
    /* each paragraph is checked in its own language */
    const char *text = "Данный подход работает.\n\nThis is a very good approach.";
    rdktr_match m[MAX_MATCHES];
    size_t n = rdktr_multi_check(M, text, strlen(text), m, MAX_MATCHES);
    CHECK(n == 2, "want 2 matches, got %zu", n);
    if (n == 2) {
        CHECK(strcmp(rdktr_multi_rule_lang(M, m[0].rule_id), "ru") == 0, "ru");
        CHECK(strcmp(rdktr_multi_rule_lang(M, m[1].rule_id), "en") == 0, "en");
    }
    /* a foreign word inside a paragraph is not checked */
    EXPECT_TOTAL("Мы сделали это very аккуратно и очень быстро", 2);
    /* ambiguous paragraph falls back to the document-dominant language */
    EXPECT("Данный текст написан по-русски.\n\nвы ok", 1, "вы",
           "Личное местоимение");
}

static void test_apostrophes(void) {
    /* rule is "don*t miss out": * = optional apostrophe */
    EXPECT("don't miss out", 0, "don't miss out", "Marketing hype");
    EXPECT("don\xE2\x80\x99t miss out", 0, "don\xE2\x80\x99t miss out",
           "Marketing hype"); /* typographic ’ */
    EXPECT("dont miss out", 0, "dont miss out", "Marketing hype");
}

static void test_single_language_engines(void) {
    rdktr_engine *en = rdktr_create_embedded("en");
    CHECK(en != NULL, "embedded en engine");
    CHECK(rdktr_create_embedded("de") == NULL, "unknown language rejected");
    if (en) {
        CHECK(strcmp(rdktr_lang(en), "en") == 0, "lang accessor");
        /* fixed language: no detection at all */
        rdktr_match m[4];
        size_t n = rdktr_check(en, "очень very", strlen("очень very"), m, 4);
        CHECK(n == 1, "en engine on mixed text: want 1, got %zu", n);
        rdktr_destroy(en);
    }
    CHECK(rdktr_embedded_count() == 2, "two embedded rule sets");
}

static void test_api_contract(void) {
    /* two-call pattern: counting must equal filling */
    const char *text = "Данный сервис позволяет принимать участие.";
    size_t count = rdktr_multi_check(M, text, strlen(text), NULL, 0);
    rdktr_match m[MAX_MATCHES];
    size_t filled = rdktr_multi_check(M, text, strlen(text), m, MAX_MATCHES);
    CHECK(count == filled && count == 3, "count %zu == filled %zu == 3", count,
          filled);
    /* capped output still reports the total */
    rdktr_match one;
    size_t total = rdktr_multi_check(M, text, strlen(text), &one, 1);
    CHECK(total == 3, "capped call returns total, got %zu", total);

    EXPECT_TOTAL("", 0);
    EXPECT_TOTAL(" \n\t ", 0);
    EXPECT_TOTAL("\xE2\x80\xA6\xE2\x80\x94", 0); /* …— punctuation only */

    /* malformed blobs are rejected */
    CHECK(rdktr_create(NULL, 0) == NULL, "NULL blob");
    _Alignas(4) static const uint8_t garbage[128] = {'g', 'a', 'r', 'b'};
    CHECK(rdktr_create(garbage, sizeof(garbage)) == NULL, "garbage blob");

    /* rule metadata is reachable through global ids */
    uint32_t rules = rdktr_multi_rule_count(M);
    CHECK(rules == 27, "27 embedded rules, got %u", rules);
    for (uint32_t i = 0; i < rules; i++) {
        CHECK(rdktr_multi_rule_title(M, i) != NULL, "title %u", i);
        CHECK(rdktr_multi_rule_lang(M, i) != NULL, "lang %u", i);
    }
}

int main(void) {
    M = rdktr_multi_create_default();
    if (!M) {
        printf("FAIL: rdktr_multi_create_default returned NULL\n");
        return 1;
    }
    test_exact_words_and_phrases();
    test_case_and_yo_folding();
    test_phrase_gaps();
    test_declensions();
    test_prefixes();
    test_word_boundaries();
    test_overlaps();
    test_comma_rule();
    test_language_detection();
    test_apostrophes();
    test_single_language_engines();
    test_api_contract();
    rdktr_multi_destroy(M);

    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
