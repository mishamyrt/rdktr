// @ts-check
import { exec } from 'child_process';
import { mkdir, readdir, stat } from 'fs/promises';
import { existsSync } from 'fs';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export const CORE_DIR = resolve(__dirname, '../../../core');
export const CORE_SRC_DIR = join(CORE_DIR, 'src');
export const CORE_INCLUDE_DIR = join(CORE_DIR, 'include');
const CORE_EXPORT_SYMBOLS = [
  'rdktr_multi_create_default',
  'rdktr_multi_check',
  'rdktr_multi_destroy',
  'rdktr_multi_rule_count',
  'rdktr_multi_rule_title',
  'rdktr_multi_rule_description',
  'rdktr_multi_rule_weight',
  'rdktr_multi_rule_lang',
  'rdktr_create',
  'rdktr_check',
  'rdktr_destroy',
  'malloc',
  'free',
]

if (import.meta.main) {
  if (process.argv.length < 3) {
    console.error('Usage: node build.js <target>');
    process.exit(1);
  }
  const targetPath = process.argv[2];
  const result = await build(targetPath);
  console.log(formatBuildResult(targetPath, result));
}

/**
 * @typedef {Object} TargetSize
 * @property {number} gzip - output file gzip size in bytes
 * @property {number} raw - output file size in bytes
 */

/**
 * @typedef {Object} BuildResult
 * @property {number} duration - build duration in milliseconds
 * @property {TargetSize} size - output file size in bytes
 */

 /**
  * Format build result for logging
  * @param {string} target - output file path
  * @param {BuildResult} result
  * @returns
  */
export function formatBuildResult(target, { duration, size }) {
  const rawSize = humanizeSize(size.raw);
  const gzipSize = humanizeSize(size.gzip)
  return `${target} ${rawSize} bytes | gzip: ${gzipSize}\n✓ built in ${duration.toFixed(2)}ms`;
}

/**
 *
 * @param {string} target - output file path
 */
export async function build(target) {
  const targetParts = target.split('/');
  if (targetParts.length > 1) {
    const parentDir = dirname(target);
    if (!existsSync(parentDir)) {
      await mkdir(parentDir, { recursive: true });
    }
  }

  const sources = await readdir(CORE_SRC_DIR)
      .then(files => files.filter((file) => file.endsWith('.c')))
      .then(files => files.map((file) => join(CORE_SRC_DIR, file)));

  const start = performance.now();
  await zigWasm({
    includes: [CORE_INCLUDE_DIR],
    exports: CORE_EXPORT_SYMBOLS,
    outputFile: target,
    sources,
  })
  const end = performance.now();
  const duration = end - start;
  const gzip = await gzipFileSize(target);
  const outStat = await stat(target);

  return {
    duration,
    size: {
      raw: outStat.size,
      gzip,
    },
  };
}

/**
 * Zig compiler options.
 *
 * @typedef {Object} BuildOptions
 * @property {string[]} sources - source files
 * @property {string[]} includes - include directories
 * @property {string[]} exports - exported symbols
 * @property {string} outputFile - output file path
 */


/**
 * Builds a WASM module using Zig.
 *
 * @param {BuildOptions} options
 */
async function zigWasm(options) {
  const includeFlags = options.includes.map((dir) => `-I"${dir}"`);
  const sources = options.sources.map((file) => `"${file}"`);
  const exportFlags = options.exports.map((sym) => `-Wl,--export=${sym}`)
  const wasmFlags = ['-target wasm32-wasi', '-mexec-model=reactor'];
  const optimizationFlags = ['-Oz', '-flto', '-Wl,--strip-all'];

  const flags = [
    wasmFlags,
    optimizationFlags,
    includeFlags,
    sources,
    exportFlags,
    `-o "${options.outputFile}"`,
  ].flat();

  await sh(`zig cc ${flags.join(' ')} -o "${options.outputFile}"`);
}

/**
 * Returns the gzipped size of a file.
 *
 * @param {string} file
 * @returns {Promise<number>}
 */
async function gzipFileSize(file) {
  const gzip = await sh(`gzip -c "${file}" | wc -c`);
  return parseInt(gzip.trim());
}

/**
 * Humanizes a size in bytes.
 *
 * @param {number} size
 * @returns {string}
 */
function humanizeSize(size) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(2)} kB`;
  }
  return `${(size / 1024 / 1024).toFixed(2)} mB`;
}

/**
 * Async runs a shell command and returns the output.
 *
 * @param {string} cmd
 * @returns {Promise<string>}
 */
function sh(cmd) {
    return new Promise((resolve, reject) => {
        exec(cmd, (error, stdout, stderr) => {
            if (error) {
                reject(error);
                return;
            }
            if (stderr) {
                reject(stderr);
                return;
            }
            resolve(stdout);
        });
    });
}
