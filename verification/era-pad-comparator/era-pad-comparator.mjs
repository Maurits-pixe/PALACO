import { createHash } from 'node:crypto';

export const SCHEMA_VERSION = 'ERA_PAD_COMPARATOR_V1';
export const MAX_INPUT_BYTES = 16_384;
export const MAX_RAW_BYTES = 4096;

const codes = new Set(['PASS', 'FAIL', 'UNKNOWN', 'ERROR', 'TIMEOUT']);
const id = value => typeof value === 'string' && /^[A-Za-z0-9._:-]{1,128}$/.test(value);
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const member = (value, values) => typeof value === 'string' && values.includes(value);

function shape(value, names) {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  const keys = Reflect.ownKeys(value);
  const expected = names.split(' ');
  if (keys.length !== expected.length || keys.some(key => !expected.includes(key))) return false;
  return keys.every(key => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor.enumerable && Object.hasOwn(descriptor, 'value');
  });
}

function timestamp(value) {
  if (value === null) return true;
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value)) return false;
  const millis = Date.parse(value);
  return Number.isFinite(millis) && new Date(millis).toISOString() === value;
}

function uncertainty(value) {
  if (value === null) return true;
  return shape(value, 'value unit')
    && typeof value.value === 'number' && Number.isFinite(value.value)
    && value.value >= 0 && !Object.is(value.value, -0)
    && member(value.unit, ['ms', 's'])
    && value.value * (value.unit === 's' ? 1000 : 1) <= 86_400_000;
}

function valid(input) {
  if (!shape(input, 'schema_version classification source_authenticity assessment_id request_digest pad temporal')) return false;
  if (input.schema_version !== SCHEMA_VERSION || input.classification !== 'SYNTHETIC_ONLY'
    || input.source_authenticity !== 'UNVERIFIED' || !id(input.assessment_id) || !digest(input.request_digest)) return false;
  const { pad, temporal } = input;
  if (!shape(pad, 'assessment_id request_digest observation_id raw_result raw_result_sha256 normalized_result')
    || !shape(temporal, 'assessment_id request_digest source_kind observed_at recorded_at sync_status uncertainty')) return false;
  if (!id(pad.assessment_id) || !digest(pad.request_digest) || !id(pad.observation_id)
    || typeof pad.raw_result !== 'string' || pad.raw_result.length > MAX_RAW_BYTES
    || !pad.raw_result.isWellFormed()
    || Buffer.byteLength(pad.raw_result, 'utf8') > MAX_RAW_BYTES
    || !digest(pad.raw_result_sha256) || !codes.has(pad.normalized_result)
    || !id(temporal.assessment_id) || !digest(temporal.request_digest)
    || !member(temporal.source_kind, ['SYNTHETIC_FIXTURE', 'UNKNOWN'])
    || !timestamp(temporal.observed_at) || !timestamp(temporal.recorded_at)
    || !member(temporal.sync_status, ['SYNCHRONIZED', 'UNSYNCHRONIZED', 'UNKNOWN'])
    || !uncertainty(temporal.uncertainty)) return false;
  return Buffer.byteLength(JSON.stringify(input), 'utf8') <= MAX_INPUT_BYTES;
}

function boundary() {
  return {
    classification: 'SYNTHETIC_ONLY', source_authenticity: 'UNVERIFIED',
    disposition: 'HOLD', operativeAuthority: 'NONE', canOpenContact: false,
    runtimeConnected: false, externalSideEffect: false, commit_order: 'UNKNOWN',
  };
}

/** Pure synthetic consistency comparison; no clock, I/O, evidence issuance or authority. */
export function compareEraPad(input) {
  const rejected = {
    ...boundary(), result: 'REJECTED', reason: 'INVALID_INPUT',
    binding_status: 'UNKNOWN', temporal_status: 'UNKNOWN', pad_status: 'UNKNOWN',
    integrity_status: 'UNKNOWN', normalization_status: 'UNKNOWN',
  };
  try {
    if (!valid(input)) return rejected;
    // Copy the fixed JSON-only structure before deriving diagnostics or returning it.
    const { pad, temporal, assessment_id, request_digest } = JSON.parse(JSON.stringify(input));
    const binding = [pad, temporal].every(item => item.assessment_id === assessment_id && item.request_digest === request_digest);
    const integrity = createHash('sha256').update(pad.raw_result, 'utf8').digest('hex') === pad.raw_result_sha256;
    const rawCode = codes.has(pad.raw_result) ? pad.raw_result : 'UNKNOWN';
    const normalized = rawCode === pad.normalized_result;
    const knownTime = temporal.source_kind === 'SYNTHETIC_FIXTURE'
      && temporal.observed_at !== null && temporal.recorded_at !== null
      && temporal.sync_status === 'SYNCHRONIZED' && temporal.uncertainty !== null
      && temporal.uncertainty.value === 0;
    return {
      ...boundary(),
      result: !binding ? 'REJECTED' : !integrity ? 'INTEGRITY_MISMATCH'
        : !normalized ? 'REJECTED' : 'CONSISTENT_SYNTHETIC_ONLY',
      reason: !binding ? 'BINDING_MISMATCH' : !integrity ? 'INTEGRITY_MISMATCH'
        : !normalized ? 'NORMALIZATION_MISMATCH' : null,
      binding_status: binding ? 'MATCH' : 'MISMATCH',
      temporal_status: knownTime ? 'KNOWN' : 'UNKNOWN',
      pad_status: rawCode,
      integrity_status: integrity ? 'MATCH' : 'INTEGRITY_MISMATCH',
      normalization_status: normalized ? 'MATCH' : 'MISMATCH',
      pad, temporal,
    };
  } catch {
    return rejected;
  }
}
