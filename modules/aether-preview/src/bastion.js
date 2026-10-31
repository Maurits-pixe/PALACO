import { isEncryptedEnvelope } from './envelope.js';

export async function createBastionTask(description, {
  baseUrl = import.meta.env?.VITE_BASTION_API_URL || '/api',
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!isEncryptedEnvelope(description)) throw new Error('Er is geen geldige versleutelde tekst.');
  if (typeof baseUrl !== 'string' || !baseUrl.trim()) throw new Error('Bastion API-URL ontbreekt.');
  let url;
  try {
    url = new URL(`${baseUrl.replace(/\/+$/, '')}/tasks`, globalThis.location?.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || (globalThis.location?.protocol === 'https:' && url.protocol !== 'https:')) throw new Error();
  } catch {
    throw new Error('Bastion API-URL is ongeldig.');
  }
  try {
    const response = await fetchImpl(url.href, {
      method: 'POST', credentials: 'omit', redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Aether — versleuteld bericht', description }),
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error();
    const task = await response.json();
    if (typeof task.id !== 'string' || !task.id || task.description !== description) throw new Error();
    return task;
  } catch {
    throw new Error('Geen bevestiging van Bastion ontvangen. Controleer Bastion voordat je opnieuw probeert; de taak kan al zijn opgeslagen.');
  }
}
