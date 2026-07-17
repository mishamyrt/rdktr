import "./style.css";
import "./editor.css";
import "./hints.css";

import { Checker, createChecker } from "../../../bindings/js/src/index.js";

const textEl = document.getElementById("text")!;
const cardsEl = document.getElementById("cards")!;

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const esc = (s: string) => s.replace(/[&<>]/g, (c) => ESCAPES[c]);

// Rule weight → severity colour class. 100 → red, 50–80 → orange, 0 → blue.
const weightClass = (weight: number) => weight >= 100 ? "w-red" : weight >= 50 ? "w-orange" : "w-blue";

// Absolute caret offset (in characters) within an element, and the inverse.
function getCaret(root: HTMLElement) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!root.contains(range.endContainer)) return null;
    const pre = range.cloneRange();
    pre.selectNodeContents(root);
    pre.setEnd(range.endContainer, range.endOffset);
    return pre.toString().length;
}

function setCaret(root: HTMLElement, offset: number) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node, count = 0, last = null;
    while ((node = walker.nextNode())) {
        last = node;
        const next = count + node.textContent!.length;
        if (offset <= next) {
            const range = document.createRange();
            range.setStart(node, offset - count);
            range.collapse(true);
            const sel = window.getSelection();
            sel!.removeAllRanges();
            sel!.addRange(range);
            return;
        }
        count = next;
    }
    const range = document.createRange();
    if (last) range.setStart(last, last.textContent!.length);
    else range.setStart(root, 0);
    range.collapse(true);
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);
}

function render(checker: Checker, text: string) {
    const caret = getCaret(textEl);
    const issues = checker.check(text);

    // Merge overlapping issues into spans; each span keeps the set of rules it
    // covers and the max weight among them (drives the highlight colour).
    const spans = [];
    for (const it of issues) {
        const last = spans[spans.length - 1];
        if (last && it.start < last.end) {
            last.end = Math.max(last.end, it.end);
            last.rules.add(it.rule.id);
            last.weight = Math.max(last.weight, it.rule.weight);
            continue;
        }
        spans.push({ start: it.start, end: it.end, rules: new Set([it.rule.id]), weight: it.rule.weight });
    }

    // Unique problems (deduped by rule), in order of first appearance.
    const order = [];
    const byRule = new Map();
    for (const it of issues) {
        let rec = byRule.get(it.rule.id);
        if (!rec) {
            rec = { rule: it.rule, count: 0 };
            byRule.set(it.rule.id, rec);
            order.push(it.rule.id);
        }
        rec.count++;
    }

    // Render the text with interactive marks.
    let html = "";
    let pos = 0;
    for (const s of spans) {
        html += esc(text.slice(pos, s.start));
        const rules = [...s.rules].join(",");
        html += `<mark class="${weightClass(s.weight)}" data-rules="${rules}">${esc(text.slice(s.start, s.end))}</mark>`;
        pos = s.end;
    }
    html += esc(text.slice(pos));
    textEl.innerHTML = html;
    if (caret !== null) setCaret(textEl, caret);

    // Render the cards.
    if (!order.length) {
        cardsEl.innerHTML = `<div class="empty">Чисто — стоп-слов не найдено.</div>`;
        return;
    }
    cardsEl.innerHTML = order.map((id) => {
        const { rule, count } = byRule.get(id);
        const badge = count > 1 ? `<span class="count">${count}</span>` : "";
        return `<div class="card ${weightClass(rule.weight)}" data-rule="${id}">
            <div class="card-title">
                <span>${esc(rule.title)}</span>
                ${badge}
            </div>
            <div class="card-hint">${esc(rule.hint)}</div>
        </div>`;
    }).join("");

    wireHover();
}

function wireHover() {
    const marks = Array.from<HTMLElement>(textEl.querySelectorAll("mark"));
    const cards = Array.from<HTMLElement>(cardsEl.querySelectorAll(".card"));
    const cardByRule = new Map(cards.map((c) => [c.dataset.rule, c]));
    const marksByRule = new Map();
    for (const m of marks) {
        for (const id of m.dataset.rules!.split(",")) {
            if (!marksByRule.has(id)) marksByRule.set(id, []);
            marksByRule.get(id).push(m);
        }
    }

    // Hover a fragment → brighten it, highlight its problem card(s).
    for (const m of marks) {
        const rules = m.dataset.rules!.split(",");
        m.addEventListener("mouseenter", () => {
            m.classList.add("hot");
            for (const id of rules) cardByRule.get(id)?.classList.add("active");
        });
        m.addEventListener("mouseleave", () => {
            m.classList.remove("hot");
            for (const id of rules) cardByRule.get(id)?.classList.remove("active");
        });
    }

    // Hover a card → highlight it, brighten every fragment of that problem.
    for (const c of cards) {
        const related = marksByRule.get(c.dataset.rule) ?? [];
        c.addEventListener("mouseenter", () => {
            c.classList.add("active");
            for (const m of related) m.classList.add("hot");
        });
        c.addEventListener("mouseleave", () => {
            c.classList.remove("active");
            for (const m of related) m.classList.remove("hot");
        });
    }
}

createChecker()
    .then((checker) => {
        textEl.setAttribute("contenteditable", "plaintext-only");
        render(checker, '');

        let composing = false;
        const update = () => { if (!composing) render(checker, textEl.textContent); };
        textEl.addEventListener("input", update);
        textEl.addEventListener("compositionstart", () => { composing = true; });
        textEl.addEventListener("compositionend", () => { composing = false; update(); });
    })
    .catch((e) => {
        textEl.innerHTML = "";
        cardsEl.innerHTML = `<div class="empty">Не удалось загрузить движок: ${esc(e.message)}</div>`;
    });
