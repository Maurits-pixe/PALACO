import assert from 'node:assert/strict'
import { test } from 'node:test'
import { encryptText, initialState, operationReducer, validateRecord } from '../src/protocol.ts'
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
