import type { Issue } from "../../../bindings/js/src/index.js";

import { weightClass } from "./weight-class";

type HighlightSpan = {
  start: number;
  end: number;
  rules: Set<number>;
  weight: number;
};

export class TextRenderer {
  private readonly containerEl: HTMLElement;

  private readonly marksByRule: Map<number, HTMLElement[]>;

  constructor(containerEl: HTMLElement) {
    this.containerEl = containerEl;

    this.marksByRule = new Map();
  }

  render(text: string, issues: readonly Issue[]) {
    this.marksByRule.clear();

    const caret = this.getCaret();
    const spans = this.calculateSpans(issues);

    const fragment = document.createDocumentFragment();

    let pos = 0;

    for (const span of spans) {
      fragment.append(text.slice(pos, span.start));

      const mark = document.createElement("mark");
      mark.className = weightClass(span.weight);
      mark.textContent = text.slice(span.start, span.end);

      const ruleIds = [...span.rules];
      mark.dataset.rules = ruleIds.join(",");

      for (const id of ruleIds) {
        this.addMark(id, mark);
      }

      fragment.append(mark);

      pos = span.end;
    }

    fragment.append(text.slice(pos));

    this.containerEl.replaceChildren(fragment);

    if (caret !== null) {
      this.setCaret(caret);
    }
  }

  clear() {
    this.marksByRule.clear();
    this.containerEl.textContent = "";
  }

  setMarkHighlighted(markEl: HTMLElement, highlight: boolean) {
    markEl.classList.toggle("hot", highlight);
  }

  setMarksHighlightedByRule(ruleId: number, highlight: boolean) {
    const marks = this.marksByRule.get(ruleId) ?? [];

    for (const mark of marks) {
      this.setMarkHighlighted(mark, highlight);
    }
  }

  private addMark(ruleId: number, mark: HTMLElement) {
    const marks = this.marksByRule.get(ruleId);

    if (marks) {
      marks.push(mark);
    } else {
      this.marksByRule.set(ruleId, [mark]);
    }
  }

  private calculateSpans(issues: readonly Issue[]) {
    const spans: HighlightSpan[] = [];

    for (const issue of issues) {
      const last = spans[spans.length - 1];

      if (last && issue.start < last.end) {
        last.end = Math.max(last.end, issue.end);
        last.rules.add(issue.rule.id);
        last.weight = Math.max(last.weight, issue.rule.weight);
        continue;
      }

      spans.push({
        start: issue.start,
        end: issue.end,
        rules: new Set([issue.rule.id]),
        weight: issue.rule.weight,
      });
    }

    return spans;
  }

  private getCaret() {
    const selection = window.getSelection();

    if (!selection || !selection.rangeCount) {
      return null;
    }

    const range = selection.getRangeAt(0);

    if (!this.containerEl.contains(range.endContainer)) {
      return null;
    }

    const beforeCaret = range.cloneRange();
    beforeCaret.selectNodeContents(this.containerEl);
    beforeCaret.setEnd(range.endContainer, range.endOffset);

    return beforeCaret.toString().length;
  }

  private setCaret(offset: number) {
    const walker = document.createTreeWalker(this.containerEl, NodeFilter.SHOW_TEXT);
    let node;
    let count = 0;
    let last = null;

    while ((node = walker.nextNode())) {
      last = node;
      const next = count + node.textContent!.length;
      if (offset <= next) {
        this.selectCaret(node, offset - count);
        return;
      }
      count = next;
    }

    this.selectCaret(last ?? this.containerEl, last?.textContent?.length ?? 0);
  }

  private selectCaret(node: Node, offset: number) {
    const range = document.createRange();
    range.setStart(node, offset);
    range.collapse(true);

    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
  }
}
