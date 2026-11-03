import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const tile = JSON.parse(readFileSync(new URL('./palaco-phone-testlab.tile.json', import.meta.url), 'utf8'));

test('tile identity and ordering remain stable', () => {
  assert.equal(tile.id, 'palaco-phone-testlab');
  assert.equal(tile.order, 15);
  assert.equal(tile.visibility, 'private');
});

test('authorization, issuance, and browser acceptance remain blocked', () => {
  assert.equal(tile.production, 'HOLD');
  assert.equal(tile.status, 'BROWSER_ACCEPTANCE_HOLD');
  assert.equal(tile.evidence.prebrowser.status, 'PASS');
  assert.notEqual(tile.evidence.ephemeralBrowser.status, 'PASS');
});

test('exactly three distinct, fixed destinations', () => {
  assert.deepEqual(tile.destinations.map(d => d.id), ['local', 'source', 'evidence']);
  assert.equal(new Set(tile.destinations.map(d => d.url)).size, 3);
  for (const d of tile.destinations) {
    assert.equal(typeof d.label, 'string');
    assert.ok(d.label.length > 5);
    const url = new URL(d.url);
    if (d.id === 'local') {
      assert.equal(url.href, 'http://127.0.0.1:8765/');
    } else {
      assert.equal(url.protocol, 'https:');
      assert.equal(url.hostname, 'github.com');
    }
  }
});

test('P.P. tile does not claim telecom service or live authentication', () => {
  assert.match(tile.description, /geen telecomnummer/i);
  assert.match(tile.destinations[0].note, /zelfde apparaat/i);
});
