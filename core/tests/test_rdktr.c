/* Behavior tests for the rdktr core. No framework: cc + run.
 *   make -C core test
 * Language bindings only need thin smoke tests on top of this suite. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rdktr.h"
#include "../src/rdktr_internal.h"

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
    EXPECT_TOTAL("Это очень важно", 2);
    EXPECT("Это очень важно", 0, "очень", "Усилители");
    EXPECT("Это очень важно", 1, "важно", "Необъективная оценка");
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
    EXPECT("существует мнение", 0, "существует", "Слабый глагол");
    /* morphology expansion inside phrases (pronouns match separately) */
    EXPECT("они принимали участие", 1, "принимали участие", "Газетный штамп");
    EXPECT("он примет участие", 1, "примет участие", "Газетный штамп");
}

static void test_prefixes(void) {
    EXPECT("высококвалифицированными", 0, "высококвалифицированными",
           "Необъективная оценка");
    EXPECT("we utilized the API", 0, "utilized", "Officialese");
    /* the stem alone is not a prefix match: needs at least one more letter */
    EXPECT_TOTAL("we utiliz it", 0);
    /* "пресловут" is a short-adjective form of ~пресловутый (lexeme, not
     * prefix), so it does match as a whole word */
    EXPECT("пресловут", 0, "пресловут", "Бытовой штамп");
}

static void test_prefixes_in_phrases(void) {
    /* rule is "сомнительн* удовольств*" */
    EXPECT("сомнительное удовольствие", 0, "сомнительное удовольствие",
           "Бытовой штамп");
    EXPECT("сомнительным удовольствием", 0, "сомнительным удовольствием",
           "Бытовой штамп");
    /* rule is "беззаботн* студенческ* жизн*" */
    EXPECT("беззаботной студенческой жизни", 0,
           "беззаботной студенческой жизни", "Газетный штамп");
    EXPECT_TOTAL("сомнительное решение", 0);
}

static void test_gaps(void) {
    /* rule is "в лучших _(0-1) традициях" */
    EXPECT("в лучших традициях", 0, "в лучших традициях", "Газетный штамп");
    EXPECT("в лучших боевых традициях", 0, "в лучших боевых традициях",
           "Газетный штамп");
    /* gap max is 1: the phrase does not fire, only standalone words do */
    EXPECT("в лучших самых боевых традициях", 0, "лучших",
           "Необъективная оценка");
    EXPECT("в лучших самых боевых традициях", 1, "самых", "Усилители");
    /* rule is "в _ жизни": the gap word may be unknown to the dictionary */
    EXPECT("в чужой жизни", 0, "в чужой жизни", "Газетный штамп");
    EXPECT_TOTAL("в жизни", 0);            /* gap needs exactly one word */
    /* punctuation breaks the gap: only the standalone word fires */
    EXPECT("в лучших, традициях", 0, "лучших", "Необъективная оценка");
    EXPECT_TOTAL("в лучших, традициях", 1);
}

static void test_punct_in_patterns(void) {
    /* rule is "все знают, что": the comma must be present in the text */
    EXPECT("все знают, что это", 0, "все знают, что", "Газетный штамп");
    /* without the comma the phrase dies; "все" alone is a generalization */
    EXPECT("все знают что это", 0, "все", "Обощение");
    EXPECT_TOTAL("все знают что это", 1);
    /* rule is "казалось,": trailing comma is part of the match */
    EXPECT("казалось, дождь", 0, "казалось,", "Газетный штамп");
    EXPECT_TOTAL("казалось солнце", 0);
}

static void test_alternatives(void) {
    /* rule is "[with|in] regard to" */
    EXPECT("with regard to", 0, "with regard to", "Officialese");
    EXPECT("in regard to", 0, "in regard to", "Officialese");
}

static void test_word_boundaries(void) {
    /* the whole word matches (~высокий), never the prefix "вы" */
    EXPECT("выше", 0, "выше", "Необъективная оценка");
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

static void test_exclamation_runs(void) {
    /* rule is "!(2+)": two or more exclamation marks in a row */
    EXPECT("Приходите завтра!! Обсудим", 0, "!!", "Слишком эмоционально");
    /* greedy: the whole run is one match */
    EXPECT("Приходите завтра!!! Обсудим", 0, "!!!", "Слишком эмоционально");
    EXPECT_TOTAL("Приходите завтра! Обсудим", 0);
    /* a word between the marks breaks the run */
    EXPECT_TOTAL("Приходите завтра! Обсудим! Потом", 0);
    /* per-language: the en rule fires on Latin paragraphs */
    EXPECT("Come tomorrow!! Sure", 0, "!!", "Too emotional");
}

static void test_parentheses(void) {
    /* rule is "\( __ \)": parens with any non-empty content */
    EXPECT("Дошли (наконец) до дома", 0, "(наконец)", "Текст в скобках");
    /* inner punctuation, including sentence dots, stays inside */
    EXPECT("Возьмите гвозди (молоток, шурупы и т. д.) с собой", 0,
           "(молоток, шурупы и т. д.)", "Текст в скобках");
    /* two groups are two separate matches */
    EXPECT_TOTAL("Раз (два) три (четыре) пять", 2);
    EXPECT("Раз (два) три (четыре) пять", 0, "(два)", "Текст в скобках");
    EXPECT("Раз (два) три (четыре) пять", 1, "(четыре)", "Текст в скобках");
    /* an unclosed or empty pair is not a match */
    EXPECT_TOTAL("Дошли (наконец до дома", 0);
    EXPECT_TOTAL("Дошли () до дома", 0);
    EXPECT("The tool (mostly) does the job", 0, "(mostly)",
           "Parenthetical aside");
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
    EXPECT_TOTAL("Мы сделали это very аккуратно и очень быстро", 3);
    /* ambiguous paragraph falls back to the document-dominant language */
    EXPECT("Данный текст написан по-русски.\n\nвы ok", 1, "вы",
           "Личное местоимение");
}

static void test_apostrophes(void) {
    /* rule is "don['|’]?t miss out": optional apostrophe variants */
    EXPECT("don't miss out", 0, "don't miss out", "Marketing hype");
    EXPECT("don\xE2\x80\x99t miss out", 0, "don\xE2\x80\x99t miss out",
           "Marketing hype"); /* typographic ’ */
    EXPECT("dont miss out", 0, "dont miss out", "Marketing hype");
}

static void test_lexemes(void) {
    /* a form shared by several lexeme sets (~он/~оно/~они) matches once */
    EXPECT_TOTAL("им", 1);
    EXPECT("им", 0, "им", "Личное местоимение");
    /* a form in the lexeme sets of two different rules: both fire */
    EXPECT_TOTAL("большею", 2);
    EXPECT("большею", 0, "большею", "Необъективная оценка");
    EXPECT("большею", 1, "большею", "Усилители");
    /* lexeme × lexeme phrase: form combinations never spelled out in rules */
    EXPECT("приняла участие", 0, "приняла участие", "Газетный штамп");
    EXPECT("принимаете участие", 0, "принимаете участие", "Газетный штамп");
}

static void test_blob_validation(void) {
    const rdktr_embedded_ruleset *ru = NULL;
    for (size_t i = 0; i < rdktr_embedded_ruleset_count; i++)
        if (strcmp(rdktr_embedded_rulesets[i].lang, "ru") == 0)
            ru = &rdktr_embedded_rulesets[i];
    CHECK(ru != NULL, "ru embedded ruleset present");
    if (!ru) return;

    uint8_t *buf = malloc(ru->size); /* malloc is at least 4-byte aligned */
    if (!buf) return;
    memcpy(buf, ru->data, ru->size);
    rdktr_engine *e = rdktr_create(buf, ru->size);
    CHECK(e != NULL, "pristine blob copy loads");
    rdktr_destroy(e);

    buf[4] ^= 0xFF; /* wrong version */
    CHECK(rdktr_create(buf, ru->size) == NULL, "wrong version rejected");
    buf[4] ^= 0xFF;

    CHECK(rdktr_create(buf, ru->size / 2) == NULL, "truncated blob rejected");

    memset(buf + 96, 0xFF, 4); /* inflated lexeme_count */
    CHECK(rdktr_create(buf, ru->size) == NULL, "bad lexeme_count rejected");

    free(buf);
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
    CHECK(rules == 39, "39 embedded rules, got %u", rules);
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
    test_prefixes_in_phrases();
    test_gaps();
    test_punct_in_patterns();
    test_alternatives();
    test_word_boundaries();
    test_overlaps();
    test_comma_rule();
    test_exclamation_runs();
    test_parentheses();
    test_language_detection();
    test_apostrophes();
    test_lexemes();
    test_blob_validation();
    test_single_language_engines();
    test_api_contract();
    rdktr_multi_destroy(M);

    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
