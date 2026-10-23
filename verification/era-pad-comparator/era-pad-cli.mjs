import { pathToFileURL } from 'node:url';
import { compareEraPad, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';
import { compareEraPadJson } from './era-pad-json.mjs';

const READ_DEADLINE_MS = 2000;
const WRITE_DEADLINE_MS = 2000;

function writeStatus(output, line) {
  return new Promise(resolve => {
    let failed = false;
    let acknowledged = false;
    const result = { ok: false, release };
    const timer = setTimeout(fail, WRITE_DEADLINE_MS);
    function release() {
      clearTimeout(timer);
      output.removeListener('error', fail);
      output.removeListener('close', fail);
    }
    function fail() {
      if (failed) return;
      failed = true;
      result.ok = false;
      release();
      // This failed, owned stream can emit an error after its callback or destroy.
      // Keep only a capture-free guard there; successful streams retain no listener.
      output.on('error', ignoreOutputError);
      try { output.destroy(); } catch {}
      resolve(result);
    }
    output.on('error', fail);
    output.on('close', fail);
    if (output.destroyed || !output.writable || output.writableEnded) {
      fail();
      return;
    }
    try {
      output.write(line, error => {
        if (error) {
          fail();
        } else if (!failed && !acknowledged) {
          acknowledged = true;
          result.ok = true;
          clearTimeout(timer);
          resolve(result);
        }
      });
    } catch {
      fail();
    }
  });
}

function ignoreOutputError() {}

function readInput(input) {
  return new Promise(resolve => {
    const chunks = [];
    let size = 0;
    let finished = false;
    const timer = setTimeout(() => finish(null), READ_DEADLINE_MS);
    function finish(bytes) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      input.removeListener('data', data);
      input.removeListener('end', end);
      input.removeListener('close', close);
      input.destroy();
      resolve(bytes);
    }
    function data(chunk) {
      if (!(chunk instanceof Uint8Array) || chunk.byteLength > MAX_INPUT_BYTES - size) {
        finish(null);
        return;
      }
      size += chunk.byteLength;
      chunks.push(Buffer.from(chunk));
    }
    function end() { finish(Buffer.concat(chunks, size)); }
    function close() { finish(null); }
    input.on('error', () => finish(null));
    input.on('data', data);
    input.once('end', end);
    input.once('close', close);
  });
}

/** Offline status-only CLI; importing this module performs no input or output. */
export async function main() {
  let report;
  if (process.argv.length !== 2) {
    process.stdin.destroy();
    report = compareEraPad(null);
  } else {
    const bytes = await readInput(process.stdin);
    report = bytes === null ? compareEraPad(null) : compareEraPadJson(bytes);
  }
  const { pad, temporal, ...status } = report;
  process.exitCode = 2;
  const output = await writeStatus(process.stdout, `${JSON.stringify(status)}\n`);
  if (output.ok && status.result === 'CONSISTENT_SYNTHETIC_ONLY') process.exitCode = 0;
  output.release();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
