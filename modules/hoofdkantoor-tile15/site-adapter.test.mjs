import { test } from 'node:test';
import assert from 'node:assert/strict';
import {appendPhoneTestlab,phoneTileForLanguage,LANGUAGE_CODES,TILE_ID} from './site-adapter.mjs';

const original=()=>Array.from({length:14},(_,i)=>({id:'original-'+(i+1),name:i===7?'PALACO PHONE':'PALACO '+(i+1),position:i+1}));
test('appends #15 while keeping all original references and positions',()=>{
  const before=original(), after=appendPhoneTestlab(before);
  assert.equal(before.length,14);assert.equal(after.length,15);
  for(let i=0;i<14;i++) assert.strictEqual(after[i],before[i]);
  assert.equal(after[14].id,TILE_ID);assert.equal(after[14].order,15);
});
test('all 12 languages have complete local/source/evidence actions',()=>{
  assert.equal(LANGUAGE_CODES.length,12);
  for(const lang of LANGUAGE_CODES) {
    const tile=phoneTileForLanguage(lang);
    assert.ok(tile.name.length>10);
    assert.equal(tile.links.length,3);
    assert.ok(tile.links.every(link=>link.label.length>2));
    assert.equal(tile.production,'HOLD');
    assert.equal(tile.status,'LOCAL_BROWSER_CI_PASS');
  }
});
test('no extra access, HTTP endpoints or production authority',()=>{
  const tile=phoneTileForLanguage('nl');
  assert.equal(tile.visibility,'private');
  assert.equal(tile.links[0].href,'http://127.0.0.1:8765/');
  for (const link of tile.links.slice(1))assert.equal(new URL(link.href).hostname,'github.com');
  assert.equal(tile.sourceEvidence.runId,41620060773);
});
test('duplicate integration refused without modifying original catalog',()=>{
  const before=original(), after=appendPhoneTestlab(before);
  assert.throws(()=>appendPhoneTestlab(after),/Expected 14|Duplicate/);
  assert.equal(before.length,14);
});
test('unknown Site versions fail closed',()=>{
  assert.throws(()=>appendPhoneTestlab([]),/Expected 14/);
  assert.throws(()=>appendPhoneTestlab(original().slice(0,13)),/Expected 14/);
  const withoutPhone=original().map(x=>({...x,name:'OTHER'}));
  assert.throws(()=>appendPhoneTestlab(withoutPhone),/PALACO PHONE/);
});
test('does not create duplicate original entries',()=>{
  const before=original();before[3].id=before[2].id;
  assert.throws(()=>appendPhoneTestlab(before),/duplicate IDs/);
});
