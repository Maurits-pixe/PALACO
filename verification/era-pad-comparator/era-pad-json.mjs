import { isUint8Array } from 'node:util/types';
import { compareEraPad, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';
import { validRequestReferences } from './era-pad-context-internal.mjs';

const byteLength = Object.getOwnPropertyDescriptor(
  Object.getPrototypeOf(Uint8Array.prototype), 'byteLength',
).get;

function parse(text) {
  let offset = 0;
  const fail = () => { throw new SyntaxError(); };
  function whitespace() {
    while (offset < text.length && ' \t\r\n'.includes(text[offset])) offset++;
  }
  function string() {
    const start = offset++;
    while (offset < text.length) {
      const character = text[offset++];
      if (character === '"') {
        const value = JSON.parse(text.slice(start, offset));
        if (!value.isWellFormed()) fail();
        return value;
      }
      if (character === '\\') offset++;
    }
    fail();
  }
  function value(depth) {
    whitespace();
    if (text[offset] === '{') return object(depth + 1);
    if (text[offset] === '"') return string();
    const token = /(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/y;
    token.lastIndex = offset;
    const match = token.exec(text);
    if (!match) fail();
    offset = token.lastIndex;
    const result = JSON.parse(match[0]);
    if (typeof result === 'number') {
      if (!Number.isFinite(result)) fail();
      if (result === 0 && /[1-9]/.test(match[0].split(/[eE]/, 1)[0])) fail();
    }
    return result;
  }
  function object(depth) {
    if (depth > 3 || text[offset++] !== '{') fail();
    const result = Object.create(null);
    whitespace();
    if (text[offset] === '}') { offset++; return result; }
    while (offset < text.length) {
      whitespace();
      if (text[offset] !== '"') fail();
      const key = string();
      if (Object.hasOwn(result, key)) fail();
      whitespace();
      if (text[offset++] !== ':') fail();
      result[key] = value(depth);
      whitespace();
      const separator = text[offset++];
      if (separator === '}') return result;
      if (separator !== ',') fail();
    }
    fail();
  }
  whitespace();
  const result = object(1);
  whitespace();
  if (offset !== text.length) fail();
  return result;
}

function decodeAndParse(bytes) {
  if (!isUint8Array(bytes) || byteLength.call(bytes) > MAX_INPUT_BYTES) throw new TypeError();
  const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  // Preserve a leading BOM in decoding so the strict JSON grammar rejects it.
  return parse(text);
}

function snapshotContext(context) {
  if (context === null || typeof context !== 'object') throw new TypeError();
  const prototype = Object.getPrototypeOf(context);
  if (prototype !== Object.prototype && prototype !== null) throw new TypeError();
  const keys = Reflect.ownKeys(context);
  const names = ['assessment_id', 'request_digest'];
  if (keys.length !== names.length || keys.some(key => !names.includes(key))) throw new TypeError();
  const copy = Object.create(null);
  for (const name of names) {
    const descriptor = Object.getOwnPropertyDescriptor(context, name);
    if (!descriptor || !descriptor.enumerable || !Object.hasOwn(descriptor, 'value')) throw new TypeError();
    copy[name] = descriptor.value;
  }
  if (!validRequestReferences(copy.assessment_id, copy.request_digest)) throw new TypeError();
  return copy;
}

/** Bounded byte-only JSON adapter; parse failures reuse the closed diagnostic. */
export function compareEraPadJson(bytes) {
  try {
    return compareEraPad(decodeAndParse(bytes));
  } catch {
    return compareEraPad(null);
  }
}

/** Compare root references with independently host-selected, unverified context. */
export function compareEraPadJsonForRequest(bytes, expectedContext) {
  try {
    const expected = snapshotContext(expectedContext);
    const input = decodeAndParse(bytes);
    const report = compareEraPad(input);
    if (report.reason === 'INVALID_INPUT') return report;
    if (input.assessment_id === expected.assessment_id && input.request_digest === expected.request_digest) return report;
    const { pad, temporal, ...status } = report;
    return { ...status, result: 'REJECTED', reason: 'BINDING_MISMATCH', binding_status: 'MISMATCH' };
  } catch {
    return compareEraPad(null);
  }
}
