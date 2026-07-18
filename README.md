<p align="center">
    <img src="./docs/logo.svg" width="50px" />
</p>

<h1 align="center">rdktr</h1>

<p align="center">
  <a href="https://github.com/mishamyrt/rdktr/actions/workflows/qa.yml">
    <img src="https://github.com/mishamyrt/rdktr/actions/workflows/qa.yml/badge.svg" />
  </a>
</p>


An engine and rule set for checking text for verbal clutter. Inspired by "[Glavred](https://glvrd.ru)".

- The C core and rules in binary form weigh less than 400 KB;
- Bindings for Swift and JavaScript;
- Throughput of at least 200,000 words per second.

## Rules

The [core/rules](./core/rules) folder contains rule sets for languages. Russian and English are supported. Rules are described using a custom [markup language](core/rules/README.md).

Compiling the rules requires the [uv](https://docs.astral.sh/uv/) package manager.

The checking language is determined separately for each sentence, by the dominant number of characters.

## Bindings

### Swift

rdktr is available as an SPM package. Add it to your dependencies in `Package.swift`:

```swift
.package(url: "https://github.com/mishamyrt/rdktr.git", branch: "master"),
```

And to the target where you want to use it:

```swift
.target(
    name: "MyTarget", 
    dependencies: [
        .product(name: "Rdktr", package: "rdktr"),
    ]
),
```

To check text, create a `TextChecker` instance and call the `check` function:

```swift
import Rdktr

// automatic language detection
let checker = TextChecker()!
for issue in checker.check(text) {
    print(text[issue.range], "—", issue.rule.title, "[\(issue.rule.language)]")
}

// fixed language, without detection
let ru = TextChecker(language: "ru")!
```

### JavaScript

For Node.JS and the browser there is an npm package, add it to your project dependencies:

```shell
npm install --save rdktr
```

Create a `Checker` instance and call the `check` method:

```js
import { createChecker } from "rdktr";

const checker = await createChecker();
for (const issue of checker.check(text)) {
    console.log(text.slice(issue.start, issue.end), "—", issue.rule.title, `[${issue.rule.language}]`);
}
checker.destroy();
```

### Web

If you only need to check text rather than build an application with the library, use the [website](rdktr.myrt.co). Computation happens in the browser.

## License

MIT.
