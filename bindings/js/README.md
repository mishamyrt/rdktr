# rdktr

Fast stop-word / text-cleanliness checker ("Glavred"-style) for Russian and
English. A WebAssembly build of a C core — zero dependencies, ~170 KB wasm
(rules included), works in browsers and Node.

The language is detected automatically per paragraph (Cyrillic vs Latin
script with a document-level fallback), so mixed-language documents get
Russian hints for Russian paragraphs and English hints for English ones.

## Usage

```js
import { createChecker } from "rdktr";

const checker = await createChecker();
const text = "Данный подход работает.\n\nThis is a very good approach.";

for (const issue of checker.check(text)) {
    // offsets are plain JS string indices (UTF-16 code units)
    console.log(
        text.slice(issue.start, issue.end), // "Данный", "very"
        issue.rule.title,                   // "Канцеляризм", "Intensifier"
        issue.rule.hint,                    // advice in the paragraph's language
        issue.rule.language,                // "ru", "en"
        issue.rule.weight,
    );
}

checker.destroy(); // frees wasm-side memory
```

`createChecker()` loads `rdktr.wasm` shipped with the package. Pass a URL,
`ArrayBuffer` or precompiled `WebAssembly.Module` to load it from somewhere
else (e.g. a CDN or a bundler asset).

## Building from source

The wasm module is prebuilt. To rebuild it from the C core you need
[zig](https://ziglang.org) (bundles clang + lld + wasi-libc):

```sh
npm run build
npm run test
```

Rules are Markdown files compiled ahead of time; see the monorepo root for
the rule format and the offline compiler.
