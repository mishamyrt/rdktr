/** A stop-word rule from the embedded rule set. */
export interface Rule {
    readonly id: number;
    /** Language of the rule set, e.g. "ru" or "en". */
    readonly language: string;
    readonly title: string;
    readonly hint: string;
    readonly weight: number;
}

/** A single finding. Offsets are UTF-16 code unit indices into the checked
 * string, directly usable with String.prototype.slice(). */
export interface Issue {
    readonly start: number;
    readonly end: number;
    readonly rule: Rule;
}

export declare class Checker {
    /** All rules of the embedded rule sets (ru + en). */
    readonly rules: readonly Rule[];
    /** Checks the text; language is detected per paragraph automatically. */
    check(text: string): Issue[];
    /** Frees the wasm-side state. Subsequent check() calls throw. */
    destroy(): void;
}

/**
 * Loads the wasm module and creates a checker.
 * @param source Where to load rdktr.wasm from. Defaults to dist/rdktr.wasm
 *   shipped with the package (works in both browsers and Node).
 */
export declare function createChecker(
    source?: string | URL | ArrayBuffer | Uint8Array | WebAssembly.Module,
): Promise<Checker>;
