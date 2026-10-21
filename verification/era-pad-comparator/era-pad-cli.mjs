import { pathToFileURL } from 'node:url';
import { compareEraPad, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';
import { compareEraPadJson } from './era-pad-json.mjs';

const READ_DEADLINE_MS = 2000;

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
  process.stdout.write(`${JSON.stringify(status)}\n`);
  process.exitCode = status.result === 'CONSISTENT_SYNTHETIC_ONLY' ? 0 : 2;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
