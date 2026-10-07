import { parseMetadataText } from './json-parser.js';

self.onmessage = ({ data }) => {
  try {
    self.postMessage({ ok: true, value: parseMetadataText(data) });
  } catch {
    self.postMessage({ ok: false, code: 'JSON_INVALID' });
  }
};
