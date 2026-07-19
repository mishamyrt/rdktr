// @ts-check
import { watch } from "fs/promises";

import {
  build,
  CORE_INCLUDE_DIR,
  CORE_SRC_DIR,
  formatBuildResult,
} from "./build.js";

async function main() {
  const outFile = process.argv[2];
  const /** @type {import('fs').WatchOptionsWithStringEncoding} */ watcherOptions =
      {
        recursive: true,
      };
  const watcher = concatIterators(
    watch(CORE_SRC_DIR, watcherOptions),
    watch(CORE_INCLUDE_DIR, watcherOptions),
  );

  await buildVerbose(outFile);
  for await (const _ of watcher) {
    await buildVerbose(outFile);
  }
}

/** @param {string} outFile */
async function buildVerbose(outFile) {
  let time = new Date().toLocaleTimeString();
  console.log(`[${time}] ⚙️ Rebuilding...`);
  const result = await build(outFile);
  time = new Date().toLocaleTimeString();
  clearLines(1);
  console.log(`[${time}] 🔨 Rebuilt!`);
  console.log(formatBuildResult(outFile, result));
}

/** @param {number} n */
function clearLines(n) {
  for (let i = 0; i < n; i++) {
    process.stdout.write("\x1b[1A\r");
    process.stdout.write("\x1b[K");
  }
}

/** @template T @param {AsyncIterableIterator<T>[]} iterators */
async function* concatIterators(...iterators) {
  for (const iterator of iterators) {
    for await (const value of iterator) {
      yield value;
    }
  }
}

main();
