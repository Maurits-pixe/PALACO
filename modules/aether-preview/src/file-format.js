const MAX_METADATA_BYTES = 64 * 1024 - 4;

export function packFile(file, bytes) {
  const header = new TextEncoder().encode(JSON.stringify({
    name: file.name,
    type: file.type || 'application/octet-stream'
  }));
  if (header.byteLength > MAX_METADATA_BYTES) {
    throw new Error('De bestandsmetadata is groter dan toegestaan.');
  }
  const packed = new Uint8Array(4 + header.length + bytes.length);
  new DataView(packed.buffer).setUint32(0, header.length);
  packed.set(header, 4);
  packed.set(bytes, 4 + header.length);
  return packed;
}

export function unpackFile(packed) {
  if (packed.byteLength < 4) throw new Error('Het ontsleutelde bestand is ongeldig.');
  const headerLength = new DataView(packed.buffer, packed.byteOffset, packed.byteLength).getUint32(0);
  if (headerLength > MAX_METADATA_BYTES || headerLength > packed.byteLength - 4) {
    throw new Error('Het ontsleutelde bestand is ongeldig.');
  }
  const headerStart = 4;
  const headerEnd = headerStart + headerLength;
  let header;
  try {
    header = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(packed.subarray(headerStart, headerEnd)));
  } catch {
    throw new Error('De versleutelde bestandsmetadata is ongeldig.');
  }
  if (
    !header ||
    typeof header !== 'object' ||
    Array.isArray(header) ||
    Object.keys(header).length !== 2 ||
    !Object.hasOwn(header, 'name') ||
    !Object.hasOwn(header, 'type') ||
    typeof header.name !== 'string' ||
    typeof header.type !== 'string' ||
    [...header.name].some(character => {
      if (character.length !== 1) return false;
      const codeUnit = character.charCodeAt(0);
      return codeUnit >= 0xd800 && codeUnit <= 0xdfff;
    })
  ) {
    throw new Error('De versleutelde bestandsmetadata is ongeldig.');
  }
  const name = header.name.split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f]/g, '') || 'ontsleuteld-bestand';
  const type = /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/i.test(header.type)
    ? header.type.toLowerCase()
    : 'application/octet-stream';
  return { name, type, bytes: packed.slice(headerEnd) };
}
