import type { Issue } from "../../../bindings/js/src/index.js";

import { RulesRenderer } from "./rules-renderer";
import { TextRenderer } from "./text-renderer";

export class Renderer {
  private readonly textEl: HTMLElement;
  private readonly rulesContainerEl: HTMLElement;

  private readonly text: TextRenderer;
  private readonly rules: RulesRenderer;

  constructor(
    textEl: HTMLElement,
    cardsEl: HTMLElement,
    cardTemplateEl: HTMLTemplateElement,
  ) {
    this.textEl = textEl;
    this.rulesContainerEl = cardsEl;

    this.text = new TextRenderer(textEl);
    this.rules = new RulesRenderer(cardsEl, cardTemplateEl);

    this.textEl.addEventListener("mouseover", (event) =>
      this.setMarkActive(event, true),
    );
    this.textEl.addEventListener("mouseout", (event) =>
      this.setMarkActive(event, false),
    );
    this.rulesContainerEl.addEventListener("mouseover", (event) =>
      this.setCardActive(event, true),
    );
    this.rulesContainerEl.addEventListener("mouseout", (event) =>
      this.setCardActive(event, false),
    );
  }

  render(text: string, issues: readonly Issue[]) {
    this.text.render(text, issues);
    this.rules.render(issues);
  }

  renderError(message: string) {
    this.text.clear();
    this.rules.renderError(message);
  }

  private setMarkActive(event: MouseEvent, active: boolean) {
    const mark = this.getHoveredElement(event, "mark");

    if (mark) {
      this.text.setMarkHighlighted(mark, active);

      for (const id of mark.dataset.rules!.split(",").map(Number)) {
        this.rules.setRuleHighlighted(id, active);
      }
    }
  }

  private setCardActive(event: MouseEvent, active: boolean) {
    const card = this.getHoveredElement(event, ".card");

    if (card) {
      this.rules.setRuleHighlighted(Number(card.dataset.rule), active);
      this.text.setMarksHighlightedByRule(Number(card.dataset.rule), active);
    }
  }

  private getHoveredElement(event: MouseEvent, selector: string) {
    if (!(event.target instanceof Element)) {
      return null;
    }

    const element = event.target.closest<HTMLElement>(selector);
    const related = event.relatedTarget;

    if (related instanceof Node && element?.contains(related)) {
      return null;
    }

    return element;
  }
}
