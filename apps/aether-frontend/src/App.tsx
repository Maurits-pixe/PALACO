import { useEffect, useReducer, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { compareEncryptedRecords, createRecordExport, encryptText, fetchStoredRecord, initialState, isRecordId, MAX_PLAINTEXT_BYTES, operationReducer, readRecordExport } from './protocol.ts'
import type { EncryptedRecord } from './protocol.ts'
import './App.css'

function App() {
  const [plaintext, setPlaintext] = useState('')
  const [token, setToken] = useState('')
  const [state, dispatch] = useReducer(operationReducer, initialState)
  const [copyStatus, setCopyStatus] = useState('')
  const [importedRecord, setImportedRecord] = useState<EncryptedRecord | null>(null)
  const [importStatus, setImportStatus] = useState('')
  const [importError, setImportError] = useState(false)
  const importAttempt = useRef(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const [recordId, setRecordId] = useState('')
  const [storedResult, setStoredResult] = useState<EncryptedRecord | null>(null)
  const [readStatus, setReadStatus] = useState('')
  const [readError, setReadError] = useState(false)
  const [readPending, setReadPending] = useState(false)
  const readAttempt = useRef(0)
  useEffect(() => () => { readAttempt.current += 1 }, [])
  const pending = state.phase === 'Verwerkend'
  const bytes = new TextEncoder().encode(plaintext).length
  const validInput = plaintext.trim().length > 0 && bytes <= MAX_PLAINTEXT_BYTES
  const result = state.phase === 'Voltooid' ? state.result : null
  const recordExport = result ? createRecordExport(result) : null
  const storedExport = storedResult ? createRecordExport(storedResult) : null
  const comparison = importedRecord && storedResult
    ? compareEncryptedRecords(importedRecord, storedResult) : null

  function clearReadback() {
    readAttempt.current += 1
    setStoredResult(null)
    setReadStatus('')
    setReadError(false)
    setReadPending(false)
  }

  async function fetchRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readPending || !isRecordId(recordId) || !token) return
    clearReadback()
    const attempt = readAttempt.current
    setReadPending(true)
    setReadStatus('Opgeslagen record wordt opgehaald.')
    try {
      const record = await fetchStoredRecord(recordId, token)
      if (attempt !== readAttempt.current) return
      setStoredResult(record)
      setReadStatus('Record uit de vault opgehaald. Geen cryptografische verificatie of ontsleuteling uitgevoerd.')
    } catch (error) {
      if (attempt !== readAttempt.current) return
      setReadError(true)
      setReadStatus(error instanceof Error ? error.message : 'Vault lezen mislukt; dit leesverzoek wijzigt geen records.')
    } finally {
      if (attempt === readAttempt.current) setReadPending(false)
    }
  }

  function reset() {
    dispatch({ type: 'reset' })
    setCopyStatus('')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending || !validInput || !token) return
    dispatch({ type: 'start' })
    setCopyStatus('')
    try {
      const record = await encryptText(plaintext, token)
      setPlaintext('')
      dispatch({ type: 'success', result: record })
    } catch (error) {
      dispatch({ type: 'failure', message: error instanceof Error ? error.message : 'Uitkomst onbekend. Controleer de engine voordat u opnieuw verzendt.' })
    }
  }

  async function copyResult(complete: boolean) {
    if (!result || !recordExport) return
    try {
      await navigator.clipboard.writeText(complete ? recordExport.json : result.ciphertext)
      setCopyStatus(complete ? 'Volledig versleuteld record gekopieerd.' : 'Ciphertext gekopieerd.')
    } catch {
      setCopyStatus('Kopiëren mislukt. Selecteer en kopieer de ciphertext handmatig.')
    }
  }

  async function inspectFile(file: File | undefined) {
    const attempt = ++importAttempt.current
    setImportedRecord(null)
    setImportError(false)
    setImportStatus(file ? 'Bestand wordt lokaal gelezen.' : '')
    if (!file) return
    try {
      const record = await readRecordExport(file)
      if (attempt !== importAttempt.current) return
      setImportedRecord(record)
      setImportStatus('Formaat herkend. Authenticiteit en opslag zijn niet gecontroleerd.')
    } catch (error) {
      if (attempt !== importAttempt.current) return
      setImportError(true)
      setImportStatus(error instanceof Error ? error.message : 'Het bestand kon niet worden gecontroleerd.')
    }
  }

  return (
    <main>
      <section className="engine-card" aria-labelledby="page-title">
        <header>
          <h1 id="page-title">Aether Engine</h1>
          <p className="lede">Lokale versleuteling met AES-256-GCM. Alleen ciphertext wordt opgeslagen.</p>
        </header>
      <div className="workspace">
        <section className="input-panel" aria-labelledby="token-title">
          <h2 id="token-title">Toegang tot de engine</h2>
          <label htmlFor="session-token">Sessietoken</label>
          <input id="session-token" type="password" value={token} autoComplete="off" spellCheck={false} disabled={pending}
            aria-describedby="token-help" onChange={(event) => { setToken(event.target.value); reset(); clearReadback() }} />
          <p className="hint" id="token-help">Gebruik het API-token van uw engine voor versleuteling en vault lezen. Alleen in het geheugen van dit tabblad; niet opgeslagen.</p>
          <button className="secondary" type="button" disabled={!token || pending}
            onClick={() => { setToken(''); reset(); clearReadback() }}>Token vergeten</button>
        </section>
        <section className="input-panel" aria-labelledby="input-title">
          <h2 id="input-title">Tekst versleutelen</h2>
          <form onSubmit={submit} aria-busy={pending}>
            <fieldset disabled={pending}>
              <label htmlFor="plaintext">Vertrouwelijke tekst</label>
              <textarea id="plaintext" value={plaintext} rows={6} spellCheck={false} autoComplete="off"
                aria-describedby="text-help byte-count" required onChange={(event) => { setPlaintext(event.target.value); reset() }} />
              <div className="text-meta">
                <p className="hint" id="text-help">Maximaal 32.768 UTF-8-bytes. Tekst wordt na bevestigd succes uit het invoerveld gewist.</p>
                <p className="byte-count" id="byte-count" aria-live="polite">{bytes.toLocaleString('nl-NL')} / 32.768 bytes</p>
              </div>
              {bytes > MAX_PLAINTEXT_BYTES && <p role="alert">De tekst is te groot. Verklein de invoer.</p>}
              <div className="actions">
                <button className="primary" type="submit" disabled={!validInput || !token || pending}>
                  {pending ? 'Verzoek wordt verwerkt' : 'Versleutelen en opslaan'}
                </button>
              </div>
            </fieldset>
          </form>
        </section>

        <section className="result-panel" aria-labelledby="result-title">
          <h2 id="result-title">Verwerkingsstatus</h2>
          <div className="status" role="status" aria-live="polite" aria-atomic="true">
            <strong>{state.phase}</strong>
            <span>{state.phase === 'Voltooid' ? '100%' : pending ? 'Bevestiging wordt afgewacht' : 'Geen voortgangspercentage'}</span>
          </div>
          {pending && <div role="progressbar" aria-label="Verwerkend: wachten op bevestiging van opslag"
            aria-valuemin={0} aria-valuemax={100} className="pending-note">De engine verwerkt uw verzoek. Er wordt geen voortgang geschat.</div>}
          {state.phase === 'Wachtend' && <p className="empty-state">Gereed voor uw invoer.<br />Een resultaat verschijnt pas na bevestigde versleuteling én opslag.</p>}
          {state.phase === 'Fout' && <p className="error" role="alert">{state.message}</p>}
          {result && recordExport && (
            <div className="result">
              <p className="confirmation">Versleuteling en lokale opslag bevestigd.</p>
              <dl>
                <dt>Record-ID</dt><dd>{result.id}</dd>
                <dt>Algoritme</dt><dd>{result.algorithm}</dd>
                <dt>Nonce (base64)</dt><dd>{result.nonce}</dd>
              </dl>
              <label htmlFor="ciphertext">Ciphertext (base64, inclusief authenticatietag)</label>
              <textarea id="ciphertext" value={result.ciphertext} readOnly rows={6} spellCheck={false} />
              <button className="secondary copy-button" type="button" onClick={() => copyResult(false)}>Ciphertext kopiëren</button>
              <button className="secondary copy-button" type="button" onClick={() => copyResult(true)}>Volledig record kopiëren (JSON)</button>
              <a className="secondary export-link" href={recordExport.href} download={recordExport.filename}>Versleuteld record downloaden</a>
              <p className="hint">Bewaar het volledige record met ID en nonce voor later herstel. Deze export bevat geen plaintext, sessietoken of mastersleutel en vervangt geen sleutelback-up. Lokale formaatcontrole is hieronder beschikbaar; ontsleuteling en terugzetten in de vault niet.</p>
              <p className="hint" role="status" aria-live="polite">{copyStatus}</p>
            </div>
          )}
          <p className="privacy-note">Geen gesimuleerde voortgang. Geen externe verbindingen. Bewaar uw mastersleutel veilig: zonder deze sleutel zijn opgeslagen gegevens niet te ontsleutelen.</p>
        </section>
        <section className="result-panel" aria-labelledby="readback-title">
          <h2 id="readback-title">Vaultrecord teruglezen</h2>
          <p className="hint" id="readback-help">Haal één versleuteld record op met zijn UUID. Alleen lezen, zonder ontsleuteling of cryptografische verificatie.</p>
          <form onSubmit={fetchRecord} aria-busy={readPending}>
            <label htmlFor="record-id">Opgeslagen record-UUID</label>
            <input id="record-id" value={recordId} autoComplete="off" spellCheck={false}
              aria-describedby="readback-help" onChange={(event) => { setRecordId(event.target.value); clearReadback() }} />
            <div className="actions">
              <button className="primary" type="submit" disabled={readPending || !token || !isRecordId(recordId)}>
                {readPending ? 'Record wordt opgehaald' : 'Opgeslagen record ophalen'}
              </button>
              <button className="secondary" type="button" onClick={clearReadback}>Vaultweergave wissen</button>
            </div>
          </form>
          <p className={readError ? 'error' : 'hint'} role={readError ? 'alert' : 'status'}>{readStatus}</p>
          {storedResult && storedExport && (
            <div>
              <dl>
                <dt>Opgeslagen record-ID</dt><dd>{storedResult.id}</dd>
                <dt>Algoritme</dt><dd>{storedResult.algorithm}</dd>
                <dt>Nonce (base64)</dt><dd>{storedResult.nonce}</dd>
              </dl>
              <label htmlFor="stored-ciphertext">Ciphertext uit vault (niet cryptografisch geverifieerd)</label>
              <textarea id="stored-ciphertext" value={storedResult.ciphertext} readOnly rows={6} spellCheck={false} />
              <a className="secondary export-link" href={storedExport.href} download={storedExport.filename}>Opgehaald record downloaden (JSON)</a>
            </div>
          )}
        </section>
        <section className="result-panel" aria-labelledby="import-title">
          <h2 id="import-title">Exportbestand inspecteren</h2>
          <label htmlFor="record-file">AETHER-record (JSON, maximaal 64 KiB)</label>
          <input ref={fileInput} id="record-file" type="file" accept=".json,application/json"
            aria-describedby="import-help" onChange={(event) => { void inspectFile(event.target.files?.[0]) }} />
          <p className="hint" id="import-help">Alleen lokale formaatcontrole, zonder upload of opslag. Een geldig formaat bewijst geen authenticiteit, succesvolle ontsleuteling of aanwezigheid in de vault. De waarde stored in het bestand is slechts aangeleverde metadata.</p>
          <p className={importError ? 'error' : 'hint'} role={importError ? 'alert' : 'status'}>{importStatus}</p>
          {importedRecord && (
            <div>
              <dl>
                <dt>Record-ID uit bestand</dt><dd>{importedRecord.id}</dd>
                <dt>Algoritme</dt><dd>{importedRecord.algorithm}</dd>
                <dt>Nonce (base64)</dt><dd>{importedRecord.nonce}</dd>
              </dl>
              <label htmlFor="imported-ciphertext">Ciphertext uit bestand (niet geverifieerd)</label>
              <textarea id="imported-ciphertext" value={importedRecord.ciphertext} readOnly rows={6} spellCheck={false} />
              <button className="secondary copy-button" type="button" onClick={() => {
                setRecordId(importedRecord.id)
                clearReadback()
              }}>Record-ID overnemen voor teruglezen</button>
              <p className="hint">Dit vult alleen de UUID in en wist de vorige vaultweergave. Kies daarna Opgeslagen record ophalen om met uw sessietoken de vault te lezen. Het bestand wordt niet verstuurd.</p>
            </div>
          )}
          <div role="status" aria-live="polite" aria-atomic="true">
            {comparison === 'match' && <p>Export en opgehaald vaultrecord komen exact overeen in ID, algoritme, nonce, ciphertext en status.</p>}
            {comparison === 'different-id' && <p>Niet vergelijkbaar als hetzelfde record: export en vaultweergave hebben verschillende record-ID’s.</p>}
            {comparison === 'different-content' && <p>Afwijking: dezelfde record-ID, maar nonce of ciphertext verschilt. De export komt niet overeen met het opgehaalde vaultrecord.</p>}
            {importedRecord && !storedResult && <p>Geen vergelijking beschikbaar. Haal eerst het bijbehorende vaultrecord expliciet op.</p>}
          </div>
          <p className="hint">De vergelijking gebruikt alleen de huidige bestandsweergave en het laatst opgehaalde record. Een overeenkomst bewijst geen authenticiteit, geldige AES-GCM-tag, ontsleutelbaarheid of blijvende opslag. Een afwijking verklaart niet welk exemplaar correct is.</p>
          <button className="secondary" type="button" onClick={() => {
            void inspectFile(undefined)
            if (fileInput.current) fileInput.current.value = ''
          }}>Bestandsweergave wissen</button>
        </section>
      </div>
      </section>
    </main>
  )
}

export default App
