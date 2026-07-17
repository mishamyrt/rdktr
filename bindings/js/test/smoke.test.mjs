import { test } from "node:test";
import assert from "node:assert/strict";
import { createChecker } from "../src/index.js";

test("finds stop words in both languages with correct offsets", async () => {
    const checker = await createChecker();
    const text = "Данный подход работает.\n\nThis is a very good approach.";
    const issues = checker.check(text);
    assert.equal(issues.length, 2);
    assert.equal(text.slice(issues[0].start, issues[0].end), "Данный");
    assert.equal(issues[0].rule.language, "ru");
    assert.equal(issues[0].rule.title, "Канцеляризм");
    assert.equal(text.slice(issues[1].start, issues[1].end), "very");
    assert.equal(issues[1].rule.language, "en");
    checker.destroy();
});

test("offsets are UTF-16 code units (surrogate pairs)", async () => {
    const checker = await createChecker();
    const text = "🚀🚀 это очень быстро";
    const issues = checker.check(text);
    assert.equal(issues.length, 2);
    assert.equal(text.slice(issues[0].start, issues[0].end), "очень");
    assert.equal(text.slice(issues[1].start, issues[1].end), "быстро");
    checker.destroy();
});

test("rule metadata is exposed", async () => {
    const checker = await createChecker();
    assert.equal(checker.rules.length, 39);
    assert.equal(checker.rules.filter((r) => r.language === "ru").length, 28);
    assert.equal(checker.rules.filter((r) => r.language === "en").length, 11);
    for (const rule of checker.rules) {
        assert.ok(rule.title.length > 0);
    }
    checker.destroy();
});

test("empty and clean input", async () => {
    const checker = await createChecker();
    assert.deepEqual(checker.check(""), []);
    assert.deepEqual(checker.check("Кошка спит на подоконнике."), []);
    assert.throws(() => {
        checker.destroy();
        checker.check("очень");
    });
});

test("repeated checks reuse the instance", async () => {
    const checker = await createChecker();
    for (let i = 0; i < 100; i++) {
        assert.equal(checker.check("очень интересно").length, 2);
    }
    checker.destroy();
});

test("punctuation rules: repeated marks and parentheses", async () => {
    const checker = await createChecker();
    const bang = "Приходите завтра!! Обсудим";
    let issues = checker.check(bang);
    assert.equal(issues.length, 1);
    assert.equal(bang.slice(issues[0].start, issues[0].end), "!!");
    assert.equal(issues[0].rule.title, "Слишком эмоционально");

    const paren = "Дошли (наконец) до дома";
    issues = checker.check(paren);
    assert.equal(issues.length, 1);
    assert.equal(paren.slice(issues[0].start, issues[0].end), "(наконец)");
    assert.equal(issues[0].rule.title, "Текст в скобках");
    checker.destroy();
});
