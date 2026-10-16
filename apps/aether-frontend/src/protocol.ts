export const MAX_PLAINTEXT_BYTES = 32_768
export const MAX_EXPORT_BYTES = 65_536

export type EncryptedRecord = {
  id: string
  ciphertext: string
  nonce: string
  algorithm: 'AES-256-GCM'
  status: 'stored'
}

export type OperationState =
  | { phase: 'Wachtend' }
  | { phase: 'Verwerkend' }
  | { phase: 'Voltooid'; result: EncryptedRecord }
  | { phase: 'Fout'; message: string }

export type OperationAction =
  | { type: 'reset' }
  | { type: 'start' }
  | { type: 'success'; result: EncryptedRecord }
  | { type: 'failure'; message: string }

export const initialState: OperationState = { phase: 'Wachtend' }

export function operationReducer(state: OperationState, action: OperationAction): OperationState {
  switch (action.type) {
    case 'reset': return state.phase === 'Verwerkend' ? state : initialState
    case 'start': return { phase: 'Verwerkend' }
    case 'success': return state.phase === 'Verwerkend' ? { phase: 'Voltooid', result: action.result } : state
    case 'failure': return state.phase === 'Verwerkend' ? { phase: 'Fout', message: action.message } : state
  }
}

function decodedLength(value: unknown): number {
  if (typeof value !== 'string' || value.length > 43_712 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) return -1
  try { return atob(value).length } catch { return -1 }
}

export function isRecordId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)
}

export function validateRecord(value: unknown): value is EncryptedRecord {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return Object.keys(record).sort().join(',') === 'algorithm,ciphertext,id,nonce,status'
    && typeof record.id === 'string'
    && isRecordId(record.id)
    && record.algorithm === 'AES-256-GCM' && record.status === 'stored'
    && decodedLength(record.nonce) === 12
    && decodedLength(record.ciphertext) >= 17
    && decodedLength(record.ciphertext) <= MAX_PLAINTEXT_BYTES + 16
}

export function compareEncryptedRecords(
  exported: EncryptedRecord,
  stored: EncryptedRecord,
): 'match' | 'different-id' | 'different-content' {
  if (!validateRecord(exported) || !validateRecord(stored)) {
    throw new Error('Alleen geldige versleutelde records kunnen worden vergeleken.')
  }
  if (exported.id !== stored.id) return 'different-id'
  return exported.algorithm === stored.algorithm
    && exported.nonce === stored.nonce
    && exported.ciphertext === stored.ciphertext
    && exported.status === stored.status ? 'match' : 'different-content'
}

export function createRecordExport(record: EncryptedRecord) {
  if (!validateRecord(record)) throw new Error('Geen geldig bevestigd record om te exporteren.')
  const json = JSON.stringify({
    format: 'palaco-aether-record',
    version: 1,
    keyDerivation: {
      algorithm: 'HKDF-SHA256',
      salt: 'record-id-utf8',
      info: 'aether/record/aes-256-gcm/v1',
    },
    additionalAuthenticatedData: 'record-id-utf8',
    record: {
      id: record.id,
      algorithm: record.algorithm,
      nonce: record.nonce,
      ciphertext: record.ciphertext,
      status: record.status,
    },
  }, null, 2)
  return {
    filename: `aether-${record.id}.json`,
    json,
    href: `data:application/json;charset=utf-8,${encodeURIComponent(json)}`,
  }
}

function hasExactKeys(value: unknown, keys: string[]): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...keys].sort().join(',')
}

export function parseRecordExport(text: string): EncryptedRecord {
  if (text.length > MAX_EXPORT_BYTES || new TextEncoder().encode(text).length > MAX_EXPORT_BYTES) {
    throw new Error('Het exportbestand is groter dan 64 KiB.')
  }
  let envelope: unknown
  try { envelope = JSON.parse(text) } catch { throw new Error('Het bestand bevat geen geldige JSON.') }
  if (!hasExactKeys(envelope, ['format', 'version', 'keyDerivation', 'additionalAuthenticatedData', 'record'])
    || envelope.format !== 'palaco-aether-record' || envelope.version !== 1
    || envelope.additionalAuthenticatedData !== 'record-id-utf8'
    || !hasExactKeys(envelope.keyDerivation, ['algorithm', 'salt', 'info'])
    || envelope.keyDerivation.algorithm !== 'HKDF-SHA256'
    || envelope.keyDerivation.salt !== 'record-id-utf8'
    || envelope.keyDerivation.info !== 'aether/record/aes-256-gcm/v1'
    || !validateRecord(envelope.record)) {
    throw new Error('Geen ondersteund AETHER versie-1-exportbestand.')
  }
  return envelope.record
}

export async function readRecordExport(file: Pick<File, 'size' | 'text'>): Promise<EncryptedRecord> {
  if (file.size > MAX_EXPORT_BYTES) throw new Error('Het exportbestand is groter dan 64 KiB.')
  let text: string
  try { text = await file.text() } catch { throw new Error('Het bestand kon niet lokaal worden gelezen.') }
  return parseRecordExport(text)
}

const UNKNOWN_OUTCOME = 'Uitkomst onbekend: opslag kon niet worden bevestigd. Het verzoek kan wel zijn opgeslagen. Controleer de engine voordat u opnieuw verzendt.'

export async function fetchStoredRecord(id: string, token: string): Promise<EncryptedRecord> {
  if (!isRecordId(id)) throw new Error('Gebruik een canonieke v4-UUID met kleine letters.')
  const failure = 'Vault lezen mislukt. Het record kon niet worden opgehaald; dit leesverzoek wijzigt geen records.'
  let response: Response
  try {
    response = await fetch(`/api/records/${id}`, {
      method: 'GET',
      credentials: 'omit',
      redirect: 'error',
      cache: 'no-store',
      headers: { Authorization: ['Bearer', token].join(' ') },
    })
  } catch {
    throw new Error(failure)
  }
  if (response.status === 401) throw new Error('Toegang geweigerd. Controleer uw sessietoken.')
  if (response.status === 403) throw new Error('Origin niet toegestaan. Controleer uw lokale configuratie.')
  if (response.status === 404) throw new Error('Geen opgeslagen record met deze UUID gevonden.')
  if (response.status !== 200) throw new Error(failure)
  let record: unknown
  try { record = await response.json() } catch { throw new Error(failure) }
  if (!validateRecord(record) || record.id !== id) throw new Error(failure)
  return record
}

export async function encryptText(plaintext: string, token: string): Promise<EncryptedRecord> {
  let response: Response
  try {
    response = await fetch('/api/encrypt', {
      method: 'POST',
      credentials: 'omit',
      redirect: 'error',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Authorization: ['Bearer', token].join(' ') },
      body: JSON.stringify({ plaintext }),
    })
  } catch {
    throw new Error(UNKNOWN_OUTCOME)
  }
  if (!response.ok) {
    if ([400, 401, 403, 413, 415].includes(response.status)) {
      throw new Error(response.status === 401
        ? 'Toegang geweigerd. Controleer uw sessietoken.'
        : `Verzoek geweigerd (${response.status}). Controleer uw invoer en lokale configuratie.`)
    }
    throw new Error(UNKNOWN_OUTCOME)
  }
  let record: unknown
  try { record = await response.json() } catch { throw new Error(UNKNOWN_OUTCOME) }
  if (response.status !== 201 || !validateRecord(record)) throw new Error(UNKNOWN_OUTCOME)
  return record
}
