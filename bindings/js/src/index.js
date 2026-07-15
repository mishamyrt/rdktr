const decoder = new TextDecoder();
const encoder = new TextEncoder();

export class Checker {
    #exports;
    #multi;
    #rules;

    /** @param {WebAssembly.Instance} instance */
    constructor(instance) {
        this.#exports = instance.exports;
        this.#multi = this.#exports.rdktr_multi_create_default();
        if (!this.#multi) throw new Error("rdktr: failed to load embedded rules");
        const count = this.#exports.rdktr_multi_rule_count(this.#multi);
        this.#rules = [];
        for (let i = 0; i < count; i++) {
            this.#rules.push(Object.freeze({
                id: i,
                language: this.#cString(this.#exports.rdktr_multi_rule_lang(this.#multi, i)),
                title: this.#cString(this.#exports.rdktr_multi_rule_title(this.#multi, i)),
                hint: this.#cString(this.#exports.rdktr_multi_rule_description(this.#multi, i)),
                weight: this.#exports.rdktr_multi_rule_weight(this.#multi, i),
            }));
        }
        Object.freeze(this.#rules);
    }

    get rules() {
        return this.#rules;
    }

    #memory() {
        return new Uint8Array(this.#exports.memory.buffer);
    }

    #cString(ptr) {
        const mem = this.#memory();
        let end = ptr;
        while (mem[end] !== 0) end++;
        return decoder.decode(mem.subarray(ptr, end));
    }

    /**
     * Checks text
     * @param {string} text
     * @returns {{start: number, end: number, rule: object}[]} офсеты в
     *   UTF-16 code units — можно напрямую использовать в text.slice().
     */
    check(text) {
        if (this.#multi === 0) throw new Error("rdktr: checker is destroyed");
        const bytes = encoder.encode(text);
        if (bytes.length === 0) return [];

        const textPtr = this.#exports.malloc(bytes.length);
        if (!textPtr) throw new Error("rdktr: out of wasm memory");
        this.#memory().set(bytes, textPtr);

        const count = this.#exports.rdktr_multi_check(
            this.#multi, textPtr, bytes.length, 0, 0);
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
            this.#multi, textPtr, bytes.length, matchPtr, count);
        const raw = new Uint32Array(
            this.#exports.memory.buffer, matchPtr, count * 3).slice();
        this.#exports.free(matchPtr);
        this.#exports.free(textPtr);

        // Convert UTF-8 offsets to UTF-16 offsets.
        const wanted = new Set();
        for (let k = 0; k < count; k++) {
            wanted.add(raw[k * 3]);
            wanted.add(raw[k * 3 + 1]);
        }
        const sorted = [...wanted].sort((a, b) => a - b);
        const toUtf16 = new Map();
        let bytePos = 0, utf16Pos = 0, next = 0;
        for (const ch of text) {
            while (next < sorted.length && sorted[next] === bytePos)
                toUtf16.set(sorted[next++], utf16Pos);
            const cp = ch.codePointAt(0);
            bytePos += cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
            utf16Pos += ch.length;
        }
        while (next < sorted.length && sorted[next] <= bytePos)
            toUtf16.set(sorted[next++], utf16Pos);

        const issues = [];
        for (let k = 0; k < count; k++) {
            issues.push({
                start: toUtf16.get(raw[k * 3]),
                end: toUtf16.get(raw[k * 3 + 1]),
                rule: this.#rules[raw[k * 3 + 2]],
            });
        }
        return issues;
    }

    destroy() {
        if (this.#multi !== 0) {
            this.#exports.rdktr_multi_destroy(this.#multi);
            this.#multi = 0;
        }
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
        module = await WebAssembly.compile(source);
    } else {
        const url = new URL(source ?? "../dist/rdktr.wasm", import.meta.url);
        if (url.protocol === "file:") {
            const { readFile } = await import("node:fs/promises");
            module = await WebAssembly.compile(await readFile(url));
        } else {
            try {
                module = await WebAssembly.compileStreaming(fetch(url));
            } catch {
                // no compileStreaming or the server sent a non-wasm MIME type
                module = await WebAssembly.compile(await (await fetch(url)).arrayBuffer());
            }
        }
    }
    const instance = await WebAssembly.instantiate(module, {});
    instance.exports._initialize?.();
    return new Checker(instance);
}
