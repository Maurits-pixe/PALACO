import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRecordExport, encryptText, initialState, MAX_EXPORT_BYTES, MAX_PLAINTEXT_BYTES, operationReducer, parseRecordExport, readRecordExport, validateRecord } from '../src/protocol.ts'
import type { EncryptedRecord } from '../src/protocol.ts'

const record: EncryptedRecord = {
  id: 'fab30b51-63ce-44bf-b694-161c9050944d',
  ciphertext: btoa('a'.repeat(32)),
  nonce: btoa('b'.repeat(12)),
  algorithm: 'AES-256-GCM',
  status: 'stored',
}

test('completion requires a pending real operation', () => {
  assert.equal(operationReducer(initialState, { type: 'success', result: record }), initialState)
  const pending = operationReducer(initialState, { type: 'start' })
  assert.deepEqual(pending, { phase: 'Verwerkend' })
  assert.equal(operationReducer(pending, { type: 'reset' }), pending)
  assert.deepEqual(operationReducer(pending, { type: 'success', result: record }), { phase: 'Voltooid', result: record })
  assert.deepEqual(operationReducer(pending, { type: 'failure', message: 'unknown' }), { phase: 'Fout', message: 'unknown' })
})

test('response contract rejects incomplete, malformed and unconfirmed records', () => {
  assert.ok(validateRecord(record))
  for (const value of [null, {}, { ...record, status: 'pending' }, { ...record, nonce: 'invalid' },
    { ...record, ciphertext: '' }, { ...record, id: 'not-a-uuid' }, { ...record, plaintext: 'leak' },
    { ...record, algorithm: 'AES-128-GCM' }]) assert.equal(validateRecord(value), false)
})

test('versioned export preserves every encrypted record field and its derivation contract', () => {
  const exported = createRecordExport(record)
  const envelope = JSON.parse(exported.json)
  assert.equal(exported.filename, `aether-${record.id}.json`)
  assert.equal(envelope.format, 'palaco-aether-record')
  assert.equal(envelope.version, 1)
  assert.deepEqual(envelope.record, record)
  assert.deepEqual(envelope.keyDerivation, {
    algorithm: 'HKDF-SHA256', salt: 'record-id-utf8', info: 'aether/record/aes-256-gcm/v1',
  })
  assert.equal(envelope.additionalAuthenticatedData, 'record-id-utf8')
  assert.ok(exported.href.startsWith('data:application/json;charset=utf-8,'))
  assert.equal(decodeURIComponent(exported.href.split(',')[1]), exported.json)
})

test('export rejects unconfirmed or secret-bearing records and unsafe filenames', () => {
  for (const invalid of [
    { ...record, status: 'pending' }, { ...record, id: '../../record' },
    { ...record, plaintext: 'private-input' }, { ...record, token: 'private-token' },
    { ...record, masterKey: 'private-key' }, { ...record, nonce: '' },
  ]) assert.throws(() => createRecordExport(invalid as EncryptedRecord), /Geen geldig/)
})

test('exports support the maximum ciphertext size without truncation', () => {
  const largest = { ...record, ciphertext: btoa('x'.repeat(MAX_PLAINTEXT_BYTES + 16)) }
  assert.deepEqual(JSON.parse(createRecordExport(largest).json).record, largest)
  assert.throws(() => createRecordExport({
    ...largest, ciphertext: btoa('x'.repeat(MAX_PLAINTEXT_BYTES + 17)),
  }), /Geen geldig/)
})

test('local inspection roundtrips exports including maximum-size ciphertext', () => {
  for (const value of [record, { ...record, ciphertext: btoa('x'.repeat(MAX_PLAINTEXT_BYTES + 16)) }]) {
    const { json } = createRecordExport(value)
    assert.deepEqual(parseRecordExport(json), value)
    assert.deepEqual(parseRecordExport(json.padEnd(MAX_EXPORT_BYTES, ' ')), value)
  }
})

test('inspection rejects malformed, foreign, extended and unsupported envelopes', () => {
  const envelope = JSON.parse(createRecordExport(record).json)
  for (const value of [
    null, [], record, { ...envelope, format: 'other' }, { ...envelope, version: '1' },
    { ...envelope, version: 2 }, { ...envelope, extra: true },
    { ...envelope, additionalAuthenticatedData: 'none' },
    { ...envelope, keyDerivation: { ...envelope.keyDerivation, info: 'wrong-context' } },
    { ...envelope, keyDerivation: { ...envelope.keyDerivation, salt: 'wrong-salt' } },
    { ...envelope, keyDerivation: { ...envelope.keyDerivation, algorithm: 'SHA256' } },
    { ...envelope, keyDerivation: { ...envelope.keyDerivation, extra: true } },
    { ...envelope, record: { ...record, plaintext: 'unexpected' } },
    { ...envelope, record: { ...record, nonce: 'invalid' } },
  ]) assert.throws(() => parseRecordExport(JSON.stringify(value)), /Geen ondersteund/)
  assert.throws(() => parseRecordExport('{'), /geldige JSON/)
  assert.throws(() => parseRecordExport(' '.repeat(MAX_EXPORT_BYTES + 1)), /64 KiB/)
  assert.throws(() => parseRecordExport('é'.repeat(MAX_EXPORT_BYTES / 2 + 1)), /64 KiB/)
})

test('file inspection is bounded before reading, handles read errors and performs no fetch', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => { assert.fail('Local inspection must not make network requests') }
  try {
    const { json } = createRecordExport(record)
    assert.deepEqual(await readRecordExport({ size: json.length, text: async () => json }), record)
    await assert.rejects(readRecordExport({
      size: MAX_EXPORT_BYTES + 1,
      text: async () => { assert.fail('Oversized files must not be read') },
    }), /64 KiB/)
    await assert.rejects(readRecordExport({
      size: 1, text: async () => ' '.repeat(MAX_EXPORT_BYTES + 1),
    }), /64 KiB/)
    await assert.rejects(readRecordExport({
      size: 1, text: async () => { throw new Error('read failed') },
    }), /lokaal worden gelezen/)
    await assert.rejects(readRecordExport({ size: 1, text: async () => '{' }), /geldige JSON/)
  } finally { globalThis.fetch = original }
})

test('network errors and invalid successes explicitly leave storage outcome unknown', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => { throw new TypeError('network failure') }
    await assert.rejects(encryptText('input', 'token'), /kan wel zijn opgeslagen/)
    globalThis.fetch = async () => new Response(JSON.stringify({ status: 'stored' }), { status: 201 })
    await assert.rejects(encryptText('input', 'token'), /Uitkomst onbekend/)
    globalThis.fetch = async () => new Response('unavailable', { status: 500 })
    await assert.rejects(encryptText('input', 'token'), /Uitkomst onbekend/)
    globalThis.fetch = async () => new Response('unauthorized', { status: 401 })
    await assert.rejects(encryptText('input', 'token'), /sessietoken/)
    for (const status of [400, 403, 413, 415]) {
      globalThis.fetch = async () => new Response('rejected', { status })
      await assert.rejects(encryptText('input', 'token'), new RegExp(`Verzoek geweigerd \\(${status}\\)`))
    }
    for (const status of [200, 202]) {
      globalThis.fetch = async () => new Response(JSON.stringify(record), { status })
      await assert.rejects(encryptText('input', 'token'), /Uitkomst onbekend/)
    }
    globalThis.fetch = async () => new Response('not-json', { status: 201 })
    await assert.rejects(encryptText('input', 'token'), /Uitkomst onbekend/)
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/api/encrypt')
      assert.equal(options?.credentials, 'omit')
      assert.equal(options?.redirect, 'error')
      assert.equal(options?.body, JSON.stringify({ plaintext: 'input' }))
      return new Response(JSON.stringify(record), { status: 201 })
    }
    assert.deepEqual(await encryptText('input', 'token'), record)
  } finally { globalThis.fetch = original }
})
