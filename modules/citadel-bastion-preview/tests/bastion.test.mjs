import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root = new URL('../', import.meta.url);

test('launcher identity is explicit and preview-only', () => {
  const identity = JSON.parse(fs.readFileSync(new URL('public/.well-known/palaco-app.json', root)));
  assert.deepEqual(identity, { appId: 'bastion', version: '1.0.0-preview.1', status: 'preview-blocked', description: 'Tactisch commandocentrum — geïsoleerde previewcandidate', securityLevel: 'preview-only' });
});

test('task controls cannot claim a successful mutation', () => {
  const source = fs.readFileSync(new URL('src/App.vue', root), 'utf8');
  assert.match(source, /STORAGE_EFFECT_DEADLINE_UNSUPPORTED/);
  assert.doesNotMatch(source, /const success\s*=\s*true/);
  assert.doesNotMatch(source, /task\.status\s*=\s*['"]COMPLETED/);
  assert.doesNotMatch(source, /task\.priority\s*=\s*['"]HIGH/);
});

test('source has no production endpoint or credentials', () => {
  const files = ['src/App.vue', 'src/main.js', 'vite.config.js', 'public/.well-known/palaco-app.json'];
  for (const file of files) {
    const content = fs.readFileSync(new URL(file, root), 'utf8');
    assert.doesNotMatch(content, /api\.post|fetch\(['"]https?:\/\//);
    assert.doesNotMatch(content, /BEGIN (RSA|OPENSSH) PRIVATE KEY/);
  }
});

test('static headers retain the default-deny policy', () => {
  const headers = fs.readFileSync(new URL('public/_headers', root), 'utf8');
  assert.match(headers, /Content-Security-Policy: default-src 'none'/);
  assert.match(headers, /X-Content-Type-Options: nosniff/);
  assert.match(headers, /Referrer-Policy: no-referrer/);
});
