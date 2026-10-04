import assert from 'node:assert/strict';
import test from 'node:test';
import '../studio-model.js';
const M=globalThis.PalacoDocuments;
const document=()=>({id:'DOC-original',title:'L.A.',purpose:'A sober document',citadel:'LA-001',visibility:'PRIVATE',template:'blank',status:'LOCAL_DRAFT',verification:'UNVERIFIED',authority:'NONE',creatorId:'PALACO-ID-original',revision:0,createdAt:'2026-09-30T12:00:00.000Z',updatedAt:'2026-09-30T12:00:00.000Z',blocks:[{id:'BLK-one',type:'text',text:'First content',at:'2026-09-30T12:00:00.000Z'}]});
async function resign(payload){delete payload.exportDigest;payload.exportDigest=await M.digest(payload);return JSON.stringify(payload)}
test('snapshots preserve earlier content and chain digests',async()=>{
  const one=await M.prepareRevision(document());const working=M.clone(one);working.blocks[0].text='Second content';
  const two=await M.prepareRevision(working,one);
  assert.equal(one.blocks[0].text,'First content');assert.equal(two.revision,2);assert.equal(two.parentDigest,one.digest);
  assert.equal(two.digest,await M.digest(M.withoutDigest(two)));assert.notEqual(two.digest,one.digest);
});
test('export hashes unsaved content rather than reusing a saved digest',async()=>{
  const saved=await M.prepareRevision(document()),working=M.clone(saved);working.title='Changed';
  const payload=await M.makeExport(working,null,true),read=await M.readExport(JSON.stringify(payload));
  assert.equal(payload.pendingChanges,true);assert.equal(read.title,'Changed');assert.notEqual(read.digest,saved.digest);assert.equal(saved.title,'L.A.');
});
test('import forks document identity while retaining original creator and source',async()=>{
  const original=await M.prepareRevision(document()),fork=await M.forkImport(original);
  assert.notEqual(fork.id,original.id);assert.equal(fork.creatorId,original.creatorId);assert.equal(fork.importedFrom.digest,original.digest);
  assert.equal(fork.revision,0);assert.equal(fork.authority,'NONE');assert.equal(fork.verification,'UNVERIFIED');assert.equal(original.revision,1);
});
test('changed export digest is rejected',async()=>{
  const payload=await M.makeExport(document(),null,false);payload.document.title='Tampered';
  await assert.rejects(M.readExport(JSON.stringify(payload)),/Export digest mismatch/);
});
test('document digest is checked independently of export digest',async()=>{
  const payload=await M.makeExport(document(),null,false);payload.document.title='Tampered';
  await assert.rejects(M.readExport(await resign(payload)),/Document digest mismatch/);
});
test('authority claims are rejected even with recomputed hashes',async()=>{
  const payload=await M.makeExport(document(),null,false);payload.document.authority='ADMIN';
  await assert.rejects(M.readExport(await resign(payload)),/without authority/);
});
test('remote image URLs and attribute injection are rejected',()=>{
  for(const data of ['https://example.com/private.png','data:image/png;base64,AAAA" onerror="alert(1)','data:image/svg+xml;base64,AAAA']){
    const doc=document();doc.blocks=[{id:'BLK-image',type:'image',at:doc.createdAt,data,name:'image.png',role:'source',caption:'',source:'',verification:'UNVERIFIED'}];
    assert.throws(()=>M.validateDocument(doc),/local PNG/);
  }
});
test('unknown fields and duplicate block IDs are rejected',()=>{
  const doc=document();doc.blocks.push(M.clone(doc.blocks[0]));assert.throws(()=>M.validateDocument(doc),/duplicate/);
  const injected=document();injected.blocks[0].onclick='alert(1)';assert.throws(()=>M.validateDocument(injected),/Unsupported document fields/);
});
test('unsupported schemas and invalid JSON are rejected',async()=>{
  await assert.rejects(M.readExport('{'),/valid JSON/);
  const payload=await M.makeExport(document(),null,false);payload.schema='UNKNOWN';await assert.rejects(M.readExport(await resign(payload)),/Unsupported PALACO/);
});
test('legacy exports without a document digest remain importable',async()=>{
  const payload={schema:'PALACO-CX-001/0.1',exportedAt:document().createdAt,boundary:'LOCAL EXPORT — NOT VERIFIED — NO AUTHORITY',identity:null,document:document()};
  const read=await M.readExport(await resign(payload));assert.equal(read.id,'DOC-original');
});
test('restoration creates a new sequential revision',async()=>{
  const one=await M.prepareRevision(document()),working=M.clone(one);working.title='Second';const two=await M.prepareRevision(working,one);
  const restored=M.clone(one);restored.restoredFrom={revision:one.revision,digest:one.digest};const three=await M.prepareRevision(restored,two);
  assert.equal(three.revision,3);assert.equal(three.title,'L.A.');assert.equal(three.parentDigest,two.digest);assert.equal(two.title,'Second');
});
test('export and import limits count UTF-8 bytes including pretty-print whitespace',async()=>{
  const doc=document();doc.blocks=Array.from({length:99},(_,i)=>({id:'BLK-'+i,type:'text',text:'界'.repeat(20000),at:doc.createdAt}));
  doc.blocks.push({id:'BLK-image',type:'image',at:doc.createdAt,data:'data:image/png;base64,'+'A'.repeat(2099000),name:'large.png',role:'source',caption:'',source:'',verification:'UNVERIFIED'});
  assert.ok(JSON.stringify(doc).length<8000000);
  await assert.rejects(M.makeExport(doc,null,false),/exceeds 8 MB/);
  await assert.rejects(M.readExport(JSON.stringify({document:doc})),/smaller than 8 MB/);
  const payload=await M.makeExport(document(),null,false);assert.ok(new TextEncoder().encode(JSON.stringify(payload,null,2)).byteLength<8000000);
  assert.equal((await M.readExport(JSON.stringify(payload,null,2))).id,'DOC-original');
});
