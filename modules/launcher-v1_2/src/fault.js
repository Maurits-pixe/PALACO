const MESSAGES = Object.freeze({
  TIMEOUT: 'Time-out: controle niet binnen 5 seconden afgerond.',
  TRANSPORT: 'Controle niet mogelijk: transport, CORS, TLS of redirect kon niet worden gecontroleerd.',
  BODY_READ: 'Controle niet mogelijk: de responsebody kon niet worden gelezen.',
  BODY_LIMIT: 'Metadata is groter dan de toegestane 64 KiB.',
  JSON_INVALID: 'Geen geldige JSON ontvangen.',
  PARSE_UNAVAILABLE: 'Controle niet mogelijk: JSON-worker is niet beschikbaar.',
  SCHEMA_OBJECT: 'JSON moet een object zijn.',
  SCHEMA_APP_ID: 'Veld "appId" ontbreekt of is geen string.',
  SCHEMA_STATUS: 'Veld "status" ontbreekt of is geen string.',
  IDENTITY: 'De ontvangen appId komt niet overeen met de verwachte module.',
  REDIRECT: 'Controle niet mogelijk: redirects zijn niet toegestaan.',
  INTERNAL: 'Controle niet mogelijk: de verificatie kon niet worden afgerond.',
  CANCELLED: 'Controle geannuleerd.',
  SUPERSEDED: 'Controle vervangen door een nieuwe poging.',
  DISPOSED: 'Launcher gesloten.'
});

export class VerificationFault extends Error {
  constructor(code, message = MESSAGES[code] || MESSAGES.INTERNAL) {
    super(message);
    this.name = 'VerificationFault';
    this.code = code;
  }
}

export function abortReason(signal) {
  return signal.reason instanceof VerificationFault ? signal.reason : new VerificationFault('CANCELLED');
}

// Abort also settles a non-cooperating injected promise. The real fetch/body
// reader is additionally aborted by its own signal/controller.
export function waitWithAbort(promise, signal) {
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    const onAbort = () => { cleanup(); reject(abortReason(signal)); };
    const cleanup = () => signal.removeEventListener('abort', onAbort);
    signal.addEventListener('abort', onAbort, { once: true });
    Promise.resolve(promise).then(
      value => { cleanup(); signal.aborted ? reject(abortReason(signal)) : resolve(value); },
      error => { cleanup(); reject(error); }
    );
  });
}
