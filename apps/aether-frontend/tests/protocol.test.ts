import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { once } from 'node:events'
import { test } from 'node:test'
import { compareEncryptedRecords, createRecordExport, encryptText, fetchStoredRecord, initialState, isRecordId, MAX_EXPORT_BYTES, MAX_PLAINTEXT_BYTES, operationReducer, parseRecordExport, readRecordExport, validateRecord } from '../src/protocol.ts'
import type { EncryptedRecord } from '../src/protocol.ts'

const record: EncryptedRecord = {
  id: 'fab30b51-63ce-44bf-b694-161c9050944d',
  ciphertext: btoa('a'.repeat(32)),
  nonce: btoa('b'.repeat(12)),
  algorithm: 'AES-256-GCM',
  status: 'stored',
}

test('shared token controls retain the encryption lock without locking pending readback', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /<input id="session-token"[^>]*disabled=\{pending\}/)
  assert.match(app, /<button[^>]*disabled=\{!token \|\| pending\}[\s\S]*?>Token vergeten<\/button>/)
})

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

test('comparison distinguishes exact equality, different IDs and altered encrypted content', () => {
  const imported = parseRecordExport(createRecordExport(record).json)
  assert.equal(compareEncryptedRecords(imported, { ...record }), 'match')
  assert.equal(compareEncryptedRecords(imported, {
    ...record, id: 'fab30b51-63ce-44bf-b694-161c9050944e',
  }), 'different-id')
  for (const changed of [
    { ...record, nonce: btoa('c'.repeat(12)) },
    { ...record, ciphertext: btoa('c'.repeat(32)) },
  ]) {
    assert.equal(compareEncryptedRecords(imported, changed), 'different-content')
    assert.equal(compareEncryptedRecords(changed, imported), 'different-content')
  }
})

test('comparison refuses malformed, extended or unconfirmed input on either side', () => {
  for (const value of [
    null, {}, { ...record, status: 'pending' }, { ...record, plaintext: 'unexpected' },
    { ...record, nonce: 'invalid' }, { ...record, algorithm: 'AES-128-GCM' },
  ]) {
    assert.throws(() => compareEncryptedRecords(value as EncryptedRecord, record), /Alleen geldige/)
    assert.throws(() => compareEncryptedRecords(record, value as EncryptedRecord), /Alleen geldige/)
  }
})

test('comparison of largest exported records is local and does not alter inputs', () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => { assert.fail('Comparison must not perform network requests') }
  try {
    const largest = Object.freeze({ ...record, ciphertext: btoa('x'.repeat(MAX_PLAINTEXT_BYTES + 16)) })
    const imported = Object.freeze(parseRecordExport(createRecordExport(largest).json))
    assert.equal(compareEncryptedRecords(imported, largest), 'match')
    assert.deepEqual(imported, largest)
  } finally { globalThis.fetch = original }
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

test('readback validates canonical v4 UUID locally before any network request', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => { assert.fail('Invalid UUID must not reach the network') }
  try {
    assert.equal(isRecordId(record.id), true)
    for (const id of ['', '../encrypt', `${record.id} `, record.id.toUpperCase(), record.id.replaceAll('-', ''),
      record.id.replace('-44bf-', '-14bf-'), record.id.replace('-b694-', '-7694-')]) {
      assert.equal(isRecordId(id), false)
      await assert.rejects(fetchStoredRecord(id, 'token'), /canonieke v4-UUID/)
    }
  } finally { globalThis.fetch = original }
})

test('readback uses a non-cached authenticated GET and preserves every record field', async () => {
  const original = globalThis.fetch
  const controller = new AbortController()
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, `/api/records/${record.id}`)
      assert.equal(options?.method, 'GET')
      assert.equal(options?.credentials, 'omit')
      assert.equal(options?.redirect, 'error')
      assert.equal(options?.cache, 'no-store')
      assert.deepEqual(options?.headers, { Authorization: ['Bearer', 'read-token'].join(' ') })
      assert.equal(options?.body, undefined)
      assert.equal(options?.signal, controller.signal)
      return new Response(JSON.stringify(record), { status: 200 })
    }
    assert.deepEqual(await fetchStoredRecord(record.id, 'read-token', controller.signal), record)
  } finally { globalThis.fetch = original }
})

test('pre-cancelled readback never reaches the network', async () => {
  const original = globalThis.fetch
  const controller = new AbortController()
  controller.abort()
  globalThis.fetch = async () => { assert.fail('Cancelled reads must not fetch') }
  try {
    await assert.rejects(fetchStoredRecord(record.id, 'token', controller.signal), { name: 'AbortError' })
  } finally { globalThis.fetch = original }
})

test('cancellation aborts a pending fetch without becoming a missing-record or write error', async () => {
  const original = globalThis.fetch
  const controller = new AbortController()
  let observedSignal: AbortSignal | null = null
  globalThis.fetch = async (_url, options) => new Promise<Response>((_resolve, reject) => {
    const signal = options?.signal
    assert.ok(signal)
    observedSignal = signal
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  })
  try {
    const read = fetchStoredRecord(record.id, 'token', controller.signal)
    const rejected = assert.rejects(read, { name: 'AbortError' })
    controller.abort()
    await rejected
    assert.equal(observedSignal, controller.signal)
    assert.equal(controller.signal.aborted, true)
  } finally { globalThis.fetch = original }
})

test('late fetch responses cannot succeed or report 404 after cancellation', async () => {
  const original = globalThis.fetch
  try {
    for (const status of [200, 404]) {
      const controller = new AbortController()
      let finish!: (response: Response) => void
      globalThis.fetch = async () => new Promise<Response>(resolve => { finish = resolve })
      const read = fetchStoredRecord(record.id, 'token', controller.signal)
      const rejected = assert.rejects(read, { name: 'AbortError' })
      controller.abort()
      finish(new Response(JSON.stringify(record), { status }))
      await rejected
    }
  } finally { globalThis.fetch = original }
})

test('cancellation during response parsing rejects even if body ignores the abort', async () => {
  const original = globalThis.fetch
  try {
    for (const bodyFails of [false, true]) {
      const controller = new AbortController()
      let finish!: () => void
      let started!: () => void
      const parsing = new Promise<void>(resolve => { started = resolve })
      const response = new Response(null, { status: 200 })
      response.json = () => new Promise((resolve, reject) => {
        finish = () => bodyFails ? reject(new TypeError('body failed')) : resolve(record)
        started()
      })
      globalThis.fetch = async () => response
      const read = fetchStoredRecord(record.id, 'token', controller.signal)
      const rejected = assert.rejects(read, { name: 'AbortError' })
      await parsing
      controller.abort()
      finish()
      await rejected
    }
  } finally { globalThis.fetch = original }
})

test('native fetch aborts loopback readback before headers and during body streaming', { timeout: 10_000 }, async () => {
  const original = globalThis.fetch
  try {
    for (const streamBody of [false, true]) {
      let ready!: () => void
      let disconnected!: () => void
      const received = new Promise<void>(resolve => { ready = resolve })
      const closed = new Promise<void>(resolve => { disconnected = resolve })
      const server = createServer((_request, response) => {
        response.on('close', disconnected)
        if (streamBody) {
          response.writeHead(200, { 'Content-Type': 'application/json' })
          response.write('{"id":')
        }
        ready()
      })
      server.listen(0, '127.0.0.1')
      await once(server, 'listening')
      try {
        const address = server.address()
        assert.ok(address && typeof address !== 'string')
        let bodyStarted!: () => void
        const readingBody = new Promise<void>(resolve => { bodyStarted = resolve })
        globalThis.fetch = async (url, options) => {
          const response = await original(`http://127.0.0.1:${address.port}${url}`, options)
          const json = response.json.bind(response)
          response.json = () => { bodyStarted(); return json() }
          return response
        }
        const controller = new AbortController()
        const read = fetchStoredRecord(record.id, 'loopback-test-token', controller.signal)
        const rejected = assert.rejects(read, { name: 'AbortError' })
        await received
        if (streamBody) await readingBody
        controller.abort()
        await rejected
        await closed
      } finally {
        server.closeAllConnections()
        await new Promise<void>(resolve => { server.close(() => resolve()) })
      }
    }
  } finally { globalThis.fetch = original }
})

test('readback distinguishes access and missing records, rejects wrong IDs and invalid successes without write uncertainty', async () => {
  const original = globalThis.fetch
  try {
    for (const [status, message] of [[401, /sessietoken/], [403, /Origin niet toegestaan/], [404, /Geen opgeslagen record/]] as const) {
      globalThis.fetch = async () => new Response('rejected', { status })
      await assert.rejects(fetchStoredRecord(record.id, 'token'), message)
    }
    const failure = /Vault lezen mislukt.*leesverzoek wijzigt geen records/
    for (const status of [201, 202, 204, 301, 400, 429, 500, 503]) {
      globalThis.fetch = async () => new Response(null, { status })
      await assert.rejects(fetchStoredRecord(record.id, 'token'), failure)
    }
    for (const value of [
      null, {}, { ...record, id: 'fab30b51-63ce-44bf-b694-161c9050944e' },
      { ...record, nonce: 'bad' }, { ...record, status: 'pending' }, { ...record, plaintext: 'leak' },
    ]) {
      globalThis.fetch = async () => new Response(JSON.stringify(value), { status: 200 })
      await assert.rejects(fetchStoredRecord(record.id, 'token'), failure)
    }
    globalThis.fetch = async () => new Response('invalid json', { status: 200 })
    await assert.rejects(fetchStoredRecord(record.id, 'token'), failure)
    globalThis.fetch = async () => { throw new TypeError('network or redirect error') }
    await assert.rejects(fetchStoredRecord(record.id, 'token'), failure)
  } finally { globalThis.fetch = original }
})
