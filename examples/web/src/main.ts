import "./style.css";
import "./editor.css";
import "./hints.css";

import { createChecker } from "../../../bindings/js/src/index.js";

import { Renderer } from "./renderer";

// Cache assets for offline use. The SW is only emitted in production builds.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register(`${import.meta.env.BASE_URL}sw.js`)
      .catch(() => {});
  });
}

const textEl = document.getElementById("text")!;
const cardsEl = document.getElementById("cards")!;
const cardTemplateEl = document.getElementById(
  "card-template",
)! as HTMLTemplateElement;
const renderer = new Renderer(textEl, cardsEl, cardTemplateEl);

createChecker()
  .then((checker) => {
    textEl.setAttribute("contenteditable", "plaintext-only");
    renderer.render("", checker.check(""));

    let composing = false;

    const update = () => {
      if (composing) return;
      const text = textEl.textContent;
      renderer.render(text, checker.check(text));
    };

    textEl.addEventListener("input", update);
    textEl.addEventListener("compositionstart", () => {
      composing = true;
    });
    textEl.addEventListener("compositionend", () => {
      composing = false;
      update();
    });
  })
  .catch((e) => {
    const message = e instanceof Error ? e.message : String(e);
    renderer.renderError(`Не удалось загрузить движок: ${message}`);
  });
