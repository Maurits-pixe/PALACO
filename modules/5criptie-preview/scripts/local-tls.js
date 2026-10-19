import fs from 'node:fs';
import path from 'node:path';
import { createSecureContext } from 'node:tls';

export function loadLocalTls(root) {
  const keyPath = path.join(root, 'certs', 'localhost-key.pem');
  const certPath = path.join(root, 'certs', 'localhost.pem');
  if (!fs.existsSync(keyPath) || !fs.existsSync(certPath)) {
    throw new Error('Lokale HTTPS-certificaten ontbreken. Maak certs/ aan en voer uit: mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1');
  }
  const https = { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) };
  try { createSecureContext(https); }
  catch { throw new Error('Lokale HTTPS-key/certificaatcombinatie is ongeldig.'); }
  return https;
}
