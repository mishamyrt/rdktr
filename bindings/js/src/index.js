//@ts-check
const decoder = new TextDecoder();
const encoder = new TextEncoder();

const NULL_PTR = /** @type {unknown} */ (0);

export class Checker {
  /** @type {import('./index').CoreExports} */
  #exports;

  /** @type {import('./index').MultiPtr} */
  #multi;

  /** @type {import('./index').Rule[]} */
  #rules;

  /** @param {import('./index').CoreExports} exports */
  constructor(exports) {
    this.#exports = exports;
    this.#multi = this.#exports.rdktr_multi_create_default();
    if (!this.#multi) {
      throw new Error("rdktr: failed to load embedded rules");
    }

    const count = this.#exports.rdktr_multi_rule_count(this.#multi);
    this.#rules = [];
    for (let i = 0; i < count; i++) {
      this.#rules.push(
        Object.freeze({
          id: i,
          language: this.#cString(
            this.#exports.rdktr_multi_rule_lang(this.#multi, i),
          ),
          title: this.#cString(
            this.#exports.rdktr_multi_rule_title(this.#multi, i),
          ),
          hint: this.#cString(
            this.#exports.rdktr_multi_rule_description(this.#multi, i),
          ),
          weight: this.#exports.rdktr_multi_rule_weight(this.#multi, i),
        }),
      );
    }
    Object.freeze(this.#rules);
  }

  /**
   * Get the list of rules.
   * @returns {import('./index').Rule[]}
   */
  get rules() {
    return this.#rules;
  }

  /**
   * Checks text and returns a list of issues.
   * @param {string} text
   * @returns {import('./index').Issue[]}
   */
  check(text) {
    if (this.#multi === 0) {
      throw new Error("rdktr: checker is destroyed");
    }
    const bytes = encoder.encode(text);
    if (bytes.length === 0) {
      return [];
    }

    const textPtr = this.#exports.malloc(bytes.length);
    if (!textPtr) {
      throw new Error("rdktr: out of wasm memory");
    }
    this.#memory().set(bytes, textPtr);

    const count = this.#exports.rdktr_multi_check(
      this.#multi,
      textPtr,
      bytes.length,
      0,
      0,
    );
    if (count === 0) {
      this.#exports.free(textPtr);
      return [];
    }
    const matchPtr = this.#exports.malloc(count * 12);
    if (!matchPtr) {
      this.#exports.free(textPtr);
      throw new Error("rdktr: out of wasm memory");
    }
    this.#exports.rdktr_multi_check(
      this.#multi,
      textPtr,
      bytes.length,
      matchPtr,
      count,
    );
    const raw = new Uint32Array(
      this.#exports.memory.buffer,
      matchPtr,
      count * 3,
    ).slice();
    this.#exports.free(matchPtr);
    this.#exports.free(textPtr);

    const toUtf16 = utf16Offsets(raw, count, text)

    /** @type {import('./index').Issue[]} */
    const issues = [];
    for (let k = 0; k < count; k++) {
      const start = /** @type {number} */ (toUtf16.get(raw[k * 3]));
      const end = /** @type {number} */ (toUtf16.get(raw[k * 3 + 1]));
      issues.push({
        start,
        end,
        rule: this.#rules[raw[k * 3 + 2]],
      });
    }
    return issues;
  }

  destroy() {
    if (this.#multi !== 0) {
      this.#exports.rdktr_multi_destroy(this.#multi);
      this.#multi = /** @type {import('./index').MultiPtr} */ (NULL_PTR);
    }
  }

  #memory() {
    return new Uint8Array(this.#exports.memory.buffer);
  }

  /**
   * @param {import('./index').StringPtr} ptr
   * @returns {string}
   */
  #cString(ptr) {
    const mem = this.#memory();
    let end = ptr;
    while (mem[end] !== 0) end++;
    return decoder.decode(mem.subarray(ptr, end));
  }
}

/**
 * Loads rdktr.wasm and returns a checker instance.
 *
 * @param {string | URL | ArrayBuffer | Uint8Array | WebAssembly.Module} [source]
 *   rdktr.wasm path.
 */
export async function createChecker(source) {
  let module;
  if (source instanceof WebAssembly.Module) {
    module = source;
  } else if (source instanceof ArrayBuffer || ArrayBuffer.isView(source)) {
    module = await WebAssembly.compile(/** @type {BufferSource} */ (source));
  } else {
    const url =
      source != null
        ? new URL(source, import.meta.url)
        : new URL("../dist/rdktr.wasm", import.meta.url);
    if (url.protocol === "file:") {
      // @ts-expect-error
      const { readFile } = await import("node:fs/promises");
      module = await WebAssembly.compile(await readFile(url));
    } else {
      try {
        module = await WebAssembly.compileStreaming(fetch(url));
      } catch {
        // no compileStreaming or the server sent a non-wasm MIME type
        module = await WebAssembly.compile(
          await (await fetch(url)).arrayBuffer(),
        );
      }
    }
  }

  const instance = await WebAssembly.instantiate(module, {});
  if (!instance.exports._initialize) {
    throw new Error("invalid module");
  }
  const exports = /** @type {import('./index').CoreExports} */ (/** @type {unknown} */ (instance.exports));
  exports._initialize?.();
  return new Checker(exports);
}

/**
 * Converts UTF-8 offsets to UTF-16.
 * Returns mapping from UTF-8 offsets to UTF-16 offsets.
 * @param {Uint32Array} raw
 * @param {number} count
 * @param {string} text
 * @returns {Map<number, number>}
 */
function utf16Offsets(raw, count, text) {
  const wanted = new Set();
  for (let k = 0; k < count; k++) {
    wanted.add(raw[k * 3]);
    wanted.add(raw[k * 3 + 1]);
  }
  const sorted = [...wanted].sort((a, b) => a - b);

  /** @type {Map<number, number>} */
  const toUtf16 = new Map();
  let bytePos = 0,
    utf16Pos = 0,
    next = 0;
  for (const ch of text) {
    while (next < sorted.length && sorted[next] === bytePos) {
      toUtf16.set(sorted[next++], utf16Pos);
    }
    const cp = /** @type {number} */ (ch.codePointAt(0));
    bytePos += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    utf16Pos += ch.length;
  }
  while (next < sorted.length && sorted[next] <= bytePos) {
    toUtf16.set(sorted[next++], utf16Pos);
  }

  return toUtf16;
}
