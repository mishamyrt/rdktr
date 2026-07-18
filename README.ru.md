<p align="center">
    <img src="./docs/logo.svg" width="50px" />
</p>

<h1 align="center">rdktr</h1>

<p align="center">
  <a href="https://github.com/mishamyrt/rdktr/actions/workflows/qa.yml">
    <img src="https://github.com/mishamyrt/rdktr/actions/workflows/qa.yml/badge.svg" />
  </a>
</p>


Движок и набор правил для проверки текста на наличие словесного мусора. Вдохновлён «[Главредом](https://glvrd.ru)».

- Ядро на C и правила в бинарном виде весят меньше 400 кб;
- Обвязки для Swift и JavaScript;
- Пропускная способность не менее 200 000 слов в секунду.

## Правила

В папке [core/rules](./core/rules) расположены наборы правилам для языков. Поддерживаются русский и английский языки. Для описания правил используется собственный [язык разметки](core/rules/README.md).

Для компиляции правил нужен пакетный менеджер [uv](https://docs.astral.sh/uv/).

Язык проверки определяется для каждого предложения отдельно, по доминирующему количеству символов.

## Обвязки

### Swift

rdktr доступен в виде SPM–пакета. Добавьте его в зависимости в `Package.swift`:

```swift
.package(url: "https://github.com/mishamyrt/rdktr.git", branch: "master"),
```

И в Target, в котором хотите использовать:

```swift
.target(
    name: "MyTarget", 
    dependencies: [
        .product(name: "Rdktr", package: "rdktr"),
    ]
),
```

Для проверки текста создайте экземпляр `TextChecker` и вызовите функцию `check`:

```swift
import Rdktr

// автоопределение языка
let checker = TextChecker()!
for issue in checker.check(text) {
    print(text[issue.range], "—", issue.rule.title, "[\(issue.rule.language)]")
}

// фиксированный язык, без детекции
let ru = TextChecker(language: "ru")!
```

### JavaScript

Для Node.JS и браузера есть npm–пакет, добавьте его в зависимости проекта:

```shell
npm install --save rdktr
```

Создайте Экземпляр `Checker` и вызовите метод `check`:

```js
import { createChecker } from "rdktr";

const checker = await createChecker();
for (const issue of checker.check(text)) {
    console.log(text.slice(issue.start, issue.end), "—", issue.rule.title, `[${issue.rule.language}]`);
}
checker.destroy();
```

### Веб

Если вам надо только проверить текст, а не разрабатывать приложение с библиотекой, воспользуйтесь [сайтом](rdktr.myrt.co). Вычисления происходят в браузере.

## Лицензия

MIT.
