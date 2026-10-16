import { useReducer, useState } from 'react'
import type { FormEvent } from 'react'
import { encryptText, initialState, MAX_PLAINTEXT_BYTES, operationReducer } from './protocol.ts'
import './App.css'

function App() {
  const [plaintext, setPlaintext] = useState('')
  const [token, setToken] = useState('')
  const [state, dispatch] = useReducer(operationReducer, initialState)
  const [copyStatus, setCopyStatus] = useState('')
  const pending = state.phase === 'Verwerkend'
  const bytes = new TextEncoder().encode(plaintext).length
  const validInput = plaintext.trim().length > 0 && bytes <= MAX_PLAINTEXT_BYTES
  const result = state.phase === 'Voltooid' ? state.result : null

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

  async function copyCiphertext() {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.ciphertext)
      setCopyStatus('Ciphertext gekopieerd.')
    } catch {
      setCopyStatus('Kopiëren mislukt. Selecteer en kopieer de ciphertext handmatig.')
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
        <section className="input-panel" aria-labelledby="input-title">
          <h2 id="input-title">Tekst versleutelen</h2>
          <form onSubmit={submit} aria-busy={pending}>
            <fieldset disabled={pending}>
              <label htmlFor="session-token">Sessietoken</label>
              <input id="session-token" type="password" value={token} autoComplete="off" spellCheck={false}
                aria-describedby="token-help" required onChange={(event) => { setToken(event.target.value); reset() }} />
              <p className="hint" id="token-help">Gebruik het API-token van uw engine. Alleen in het geheugen van dit tabblad; niet opgeslagen.</p>
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
                <button className="secondary" type="button" disabled={!token}
                  onClick={() => { setToken(''); reset() }}>Token vergeten</button>
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
          {result && (
            <div className="result">
              <p className="confirmation">Versleuteling en lokale opslag bevestigd.</p>
              <dl>
                <dt>Record-ID</dt><dd>{result.id}</dd>
                <dt>Algoritme</dt><dd>{result.algorithm}</dd>
                <dt>Nonce (base64)</dt><dd>{result.nonce}</dd>
              </dl>
              <label htmlFor="ciphertext">Ciphertext (base64, inclusief authenticatietag)</label>
              <textarea id="ciphertext" value={result.ciphertext} readOnly rows={6} spellCheck={false} />
              <button className="secondary copy-button" type="button" onClick={copyCiphertext}>Ciphertext kopiëren</button>
              <p className="hint" role="status" aria-live="polite">{copyStatus}</p>
            </div>
          )}
          <p className="privacy-note">Geen gesimuleerde voortgang. Geen externe verbindingen. Bewaar uw mastersleutel veilig: zonder deze sleutel zijn opgeslagen gegevens niet te ontsleutelen.</p>
        </section>
      </div>
      </section>
    </main>
  )
}

export default App
