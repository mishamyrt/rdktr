import type { Issue, Rule } from "../../../bindings/js/src/index.js";

import { weightClass } from "./weight-class";

type RenderedRule = {
  rule: Rule;
  count: number;
  card: HTMLElement;
};

export class RulesRenderer {
  private readonly containerEl: HTMLElement;
  private readonly cardTpl: HTMLTemplateElement;

  private readonly emptyEl: HTMLDivElement;
  private readonly errorEl: HTMLDivElement;

  private readonly renderedRules: Map<number, RenderedRule>;

  constructor(containerEl: HTMLElement, cardTpl: HTMLTemplateElement) {
    this.containerEl = containerEl;
    this.cardTpl = cardTpl;

    this.emptyEl = document.createElement("div");
    this.emptyEl.className = "empty";
    this.emptyEl.textContent = "Чисто — стоп-слов не найдено.";

    this.errorEl = document.createElement("div");
    this.errorEl.className = "error";

    this.renderedRules = new Map();
  }

  render(issues: readonly Issue[]) {
    const rules = new Set<number>();

    for (const issue of issues) {
      const renderedRule = this.renderedRules.get(issue.rule.id) ?? {
        rule: issue.rule,
        count: 1,
        card: this.createCard(issue.rule),
      };

      if (rules.has(issue.rule.id)) {
        renderedRule.count += 1;
      } else {
        renderedRule.count = 1;
        this.renderedRules.set(issue.rule.id, renderedRule);

        rules.add(issue.rule.id);
      }
    }

    for (const [id, renderedRule] of this.renderedRules) {
      if (!rules.has(id)) {
        renderedRule.card.remove();
        this.renderedRules.delete(id);
      }
    }

    if (rules.size === 0) {
      if (!this.emptyEl.isConnected) {
        this.containerEl.replaceChildren(this.emptyEl);
      }
      return;
    }

    this.emptyEl.remove();
    this.errorEl.remove();

    let cursor = this.containerEl.firstElementChild;

    for (const id of rules) {
      const renderedRule = this.renderedRules.get(id)!;
      this.updateCount(renderedRule.card, renderedRule.count);

      if (renderedRule.card !== cursor) {
        this.containerEl.insertBefore(renderedRule.card, cursor);
      }

      cursor = renderedRule.card.nextElementSibling;
    }
  }

  renderError(message: string) {
    this.renderedRules.clear();
    this.errorEl.textContent = message;
    this.containerEl.replaceChildren(this.errorEl);
  }

  setRuleHighlighted(ruleId: number, active: boolean) {
    const renderedRule = this.renderedRules.get(ruleId);

    if (renderedRule) {
      renderedRule.card.classList.toggle("active", active);
    }
  }

  private createCard(rule: Rule) {
    const card = this.cardTpl.content.firstElementChild!.cloneNode(true) as HTMLElement;
    card.dataset.rule = String(rule.id);
    card.classList.add(weightClass(rule.weight));

    card.querySelector<HTMLElement>(".card-name")!.textContent = rule.title;
    card.querySelector<HTMLElement>(".card-hint")!.textContent = rule.hint;

    return card;
  }

  private updateCount(card: HTMLElement, count: number) {
    const countEl = card.querySelector<HTMLElement>(".count")!;
    const value = String(count);

    if (countEl.textContent !== value) {
      countEl.textContent = value;
    }

    const hidden = count <= 1;
    if (countEl.hidden !== hidden) {
      countEl.hidden = hidden;
    }
  }
}
