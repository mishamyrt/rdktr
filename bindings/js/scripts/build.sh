#!/bin/sh
# Builds the rdktr core into a standalone WebAssembly module.
# Requires zig (bundles clang + lld + wasi-libc): https://ziglang.org
set -eu
cd "$(dirname "$0")/.."
mkdir -p dist

CORE=../../core
EXPORTS="
    rdktr_multi_create_default
    rdktr_multi_check
    rdktr_multi_destroy
    rdktr_multi_rule_count
    rdktr_multi_rule_title
    rdktr_multi_rule_description
    rdktr_multi_rule_weight
    rdktr_multi_rule_lang
    rdktr_create
    rdktr_check
    rdktr_destroy
    malloc
    free
"
EXPORT_FLAGS=""
for sym in $EXPORTS; do
    EXPORT_FLAGS="$EXPORT_FLAGS -Wl,--export=$sym"
done

# shellcheck disable=SC2086
zig cc -target wasm32-wasi -mexec-model=reactor -Oz -flto -Wl,--strip-all \
    -I"$CORE/include" \
    "$CORE/src/engine.c" \
    "$CORE/src/blob.c" \
    "$CORE/src/multi.c" \
    "$CORE/src/normalize.c" \
    "$CORE/src/rules_data.c" \
    $EXPORT_FLAGS \
    -o dist/rdktr.wasm

ls -la dist/rdktr.wasm
