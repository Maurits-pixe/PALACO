import { VerificationFault, abortReason } from './fault.js';

export function parseInWorker(text, signal) {
  if (signal.aborted) return Promise.reject(abortReason(signal));
  return new Promise((resolve, reject) => {
    let worker;
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', onAbort);
      worker?.terminate();
      error ? reject(error) : resolve(value);
    };
    const onAbort = () => finish(abortReason(signal));
    try {
      worker = new Worker(new URL('./json-worker.js', import.meta.url), { type: 'module' });
      signal.addEventListener('abort', onAbort, { once: true });
      worker.onmessage = ({ data }) => {
        if (signal.aborted) return onAbort();
        if (data?.ok === true) finish(null, data.value);
        else finish(new VerificationFault('JSON_INVALID'));
      };
      worker.onerror = () => finish(new VerificationFault('PARSE_UNAVAILABLE'));
      worker.onmessageerror = () => finish(new VerificationFault('PARSE_UNAVAILABLE'));
      worker.postMessage(text);
    } catch {
      finish(new VerificationFault('PARSE_UNAVAILABLE'));
    }
  });
}
