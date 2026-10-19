import test from 'node:test';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
import {DocumentVault,validateCatalog} from './storage-vault.mjs';
import {encodeDocument} from './document-exchange.mjs';
const ROOT='/api/storage/objects',token=Buffer.alloc(32).toString('base64url');
const ref={repository:'Maurits-pixe/PALACO',commitSha:'a'.repeat(40),path:'README.md'};
const document={documentId:'vault-fixture',title:'Storage fixture',content:'Synthetic document content.',status:'draft'};
const bytes=await encodeDocument(ref,document),digest=payload=>createHash('sha256').update(payload).digest('base64url');
const base={mode:'SYNTHETIC_ONLY',account1:'HOLD',accountActive:false,canOpenContact:false,operativeAuthority:'NONE'};
const envelope=object=>({schema:'RIO_CMV_SYNTHETIC_OBJECT_V1',...base,object});
const response=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json'}});
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
function server(){
  const state={accountId:'TST-alpha',token,calls:[],rows:[],payloads:new Map(),intercept:undefined};
  const usage=()=>({liveBytes:state.rows.reduce((n,r)=>n+r.liveBytes,0),retainedObjects:state.rows.length});
  const catalog=()=>({schema:'RIO_CMV_SYNTHETIC_CATALOG_V1',...base,observedAt:Date.now(),objects:structuredClone(state.rows),usage:usage()});
  const fetch=async(path,options)=>{
    state.calls.push({path,options});const custom=await state.intercept?.(path,options);if(custom)return custom;
    if(path==='/api/me')return response({accountId:state.accountId,csrfToken:state.token,...base,actorKind:'SYNTHETIC_DEV_ACTOR',credentialControl:'VERIFIED_DEV_OIDC'});
    if(path==='/auth/logout')return response({loggedOut:true,providerLogout:'NOT_REQUESTED',mode:'SYNTHETIC_ONLY'});
    if(path==='/api/storage/usage')return response({schema:'RIO_CMV_SYNTHETIC_OBJECT_V1',...base,usage:usage(),limits:{objectBytes:16384,liveBytes:65536,lifetimeObjects:64,retentionMs:86400000}});
    if(path===ROOT)return response(catalog());
    const id=path.slice(ROOT.length+1),row=state.rows.find(r=>r.objectId===id);
    if(options.method==='PUT'){
      const body=JSON.parse(options.body),payload=Buffer.from(body.payload,'base64url'),now=Date.now();
      if(!row){state.payloads.set(id,payload);state.rows.push({objectId:id,sha256:digest(payload),liveBytes:payload.length,state:'LIVE',createdAt:now,expiresAt:now+body.retentionMs,endedAt:null,payloadVerified:true});}
      return response(envelope({objectId:id,sha256:digest(payload),bytes:payload.length}),row?200:201);
    }
    if(!row)return response({},404);
    if(options.method==='DELETE'){
      Object.assign(row,{state:'DELETED',endedAt:Date.now(),liveBytes:0,payloadVerified:false});
      return response({...envelope({objectId:id,sha256:row.sha256,state:row.state,endedAt:row.endedAt,liveBytes:0,payloadVerified:false}),usage:usage()});
    }
    const payload=state.payloads.get(id);return response(envelope({objectId:id,sha256:row.sha256,bytes:payload.length,payload:payload.toString('base64url')}));
  };
  return {state,fetch,catalog};
}
function create(t,fixture=server(),notify){const vault=new DocumentVault(fixture.fetch,notify);t.after(()=>vault.close());return {vault,...fixture};}

test('catalog enforces complete byte totals, unique IDs, lifecycle times and closed authority',()=>{
  const now=Date.now(),id=n=>Buffer.alloc(32,n).toString('base64url');
  const live={objectId:id(1),sha256:id(2),state:'LIVE',liveBytes:100,createdAt:now-1000,expiresAt:now+59000,endedAt:null,payloadVerified:true};
  const gone={...live,objectId:id(3),state:'DELETED',liveBytes:0,endedAt:now-500,payloadVerified:false};
  const expired={...gone,objectId:id(4),state:'EXPIRED',createdAt:now-61000,expiresAt:now-1000,endedAt:now-500};
  const valid={schema:'RIO_CMV_SYNTHETIC_CATALOG_V1',...base,observedAt:now,objects:[live,gone,expired],usage:{liveBytes:100,retainedObjects:3}};
  assert.equal(validateCatalog(valid).objects.length,3);assert.ok(Object.isFrozen(validateCatalog(valid).objects[0]));
  for(const change of [v=>v.accountActive=true,v=>v.ownerId='other',v=>v.usage.liveBytes=101,v=>v.usage.retainedObjects=2,
    v=>v.objects[1].objectId=live.objectId,v=>v.objects[0].liveBytes='100',v=>v.objects[0].payloadVerified=false,
    v=>v.objects[0].endedAt=now,v=>v.objects[0].expiresAt=now,v=>v.objects[1].liveBytes=1,
    v=>v.objects[1].endedAt=live.expiresAt,v=>v.objects[2].endedAt=expired.expiresAt-1,
    v=>v.objects[2].payloadVerified=true,v=>v.objects[2].state='REMOVED',v=>v.objects[0].sha256='B'.repeat(43)]){
    const altered=structuredClone(valid);change(altered);assert.throws(()=>validateCatalog(altered));
  }
});

test('fixed-origin session, save, verified open and checked erase expose no CSRF token',async t=>{
  const {vault,state}=create(t);await vault.connect();const saved=await vault.save(bytes);
  assert.deepEqual((await vault.open(saved.objectId)).document,document);
  const terminal=await vault.erase(saved.objectId);assert.equal(terminal.state,'DELETED');
  assert.equal(vault.snapshot().document,undefined);assert.equal(vault.snapshot().catalog.usage.liveBytes,0);
  assert.equal(vault.snapshot().catalog.usage.retainedObjects,1);
  assert.equal(JSON.stringify(vault.snapshot()).includes(token),false);
  for(const {path,options} of state.calls){
    assert.ok(path.startsWith('/api/'));assert.equal(options.credentials,'same-origin');assert.equal(options.redirect,'error');
    assert.equal(options.cache,'no-store');assert.ok(options.signal instanceof AbortSignal);
    if(options.method!=='GET')assert.equal(options.headers['x-csrf-token'],token);
  }
  const deleted=state.calls.find(c=>c.options.method==='DELETE');assert.deepEqual(JSON.parse(deleted.options.body),{sha256:saved.sha256});
});

test('an uncertain committed upload retries the same object without renewing retention',async t=>{
  const fixture=server(),{vault,state}=create(t,fixture);await vault.connect();
  let lose=true;const real=fixture.fetch;
  // The actual mock server commits first; only the response is lost.
  const transport=async(path,options)=>{const result=await real(path,options);if(options.method==='PUT'&&lose){lose=false;throw Error('lost response');}return result;};
  const recovering=new DocumentVault(transport);t.after(()=>recovering.close());await recovering.connect();
  await assert.rejects(recovering.save(bytes));assert.equal(recovering.snapshot().phase,'unavailable');
  assert.equal(recovering.snapshot().pendingSave,true);assert.equal(recovering.snapshot().catalog,undefined);
  const first={...state.rows[0]};await recovering.connect();
  await assert.rejects(recovering.save(bytes,3600000),{code:'PENDING_SAVE'});
  await recovering.save(bytes);const puts=state.calls.filter(c=>c.options.method==='PUT');
  assert.equal(puts.length,2);assert.equal(puts[0].path,puts[1].path);assert.equal(puts[0].options.body,puts[1].options.body);
  assert.equal(state.rows.length,1);assert.equal(state.rows[0].createdAt,first.createdAt);assert.equal(state.rows[0].expiresAt,first.expiresAt);
  assert.equal(recovering.snapshot().pendingSave,false);
});

test('late document responses cannot restore state after close',async t=>{
  const fixture=server(),{vault,state}=create(t,fixture);await vault.connect();const row=await vault.save(bytes);
  const entered=deferred(),release=deferred();state.intercept=async(path,options)=>{
    if(path===ROOT+'/'+row.objectId&&options.method==='GET'){entered.resolve();await release.promise;}
  };
  const pending=vault.open(row.objectId);await entered.promise;vault.close();release.resolve();await assert.rejects(pending);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(vault.snapshot().phase,'closed');assert.equal(vault.snapshot().accountId,undefined);assert.equal(vault.snapshot().document,undefined);
});

test('logout preempts a held read, clears private state immediately and waits for confirmation',async t=>{
  const fixture=server(),events=[],{vault,state}=create(t,fixture,s=>events.push(s));await vault.connect();const row=await vault.save(bytes);await vault.open(row.objectId);
  const entered=deferred(),release=deferred(),logoutEntered=deferred(),logoutRelease=deferred();
  state.intercept=async(path,options)=>{
    if(path===ROOT+'/'+row.objectId&&options.method==='GET'){entered.resolve();await release.promise;}
    if(path==='/auth/logout'){logoutEntered.resolve();await logoutRelease.promise;}
  };
  const read=vault.open(row.objectId);const settled=assert.rejects(read);await entered.promise;
  const logout=vault.logout();const clearIndex=events.length-1;await logoutEntered.promise;
  assert.equal(vault.snapshot().phase,'logging-out');assert.equal(vault.snapshot().busy,true);
  assert.equal(vault.snapshot().accountId,undefined);assert.equal(vault.snapshot().catalog,undefined);assert.equal(vault.snapshot().document,undefined);
  release.resolve();logoutRelease.resolve();await Promise.all([settled,logout]);
  assert.equal(vault.snapshot().phase,'anonymous');assert.ok(events.slice(clearIndex).every(s=>!s.document&&!s.accountId&&!s.catalog));
});

test('session rotation or account replacement blocks access before a document is requested',async t=>{
  const {vault,state}=create(t);await vault.connect();const row=await vault.save(bytes);await vault.open(row.objectId);
  state.accountId='TST-beta';state.token=Buffer.alloc(32,2).toString('base64url');const start=state.calls.length;
  await assert.rejects(vault.open(row.objectId),{code:'AUTHENTICATION_REQUIRED'});
  assert.equal(vault.snapshot().phase,'anonymous');assert.equal(vault.snapshot().document,undefined);
  assert.deepEqual(state.calls.slice(start).map(c=>c.path),['/api/me']);
});

test('stream, MIME, UTF8, capacity and HTTP failures clear the catalog',async t=>{
  for(const make of [()=>new Response('x'.repeat(40001),{headers:{'content-type':'application/json'}}),
    ()=>new Response('{}',{headers:{'content-type':'text/html'}}),
    ()=>new Response(new Uint8Array([0xff]),{headers:{'content-type':'application/json'}}),
    ()=>new Response('{}',{headers:{'content-type':'application/json','content-length':'40001'}}),
    fixture=>response(fixture.catalog(),206),()=>response({},401),()=>response({},503)]){
    const fixture=server(),{vault,state}=create(t,fixture);await vault.connect();
    state.intercept=path=>path===ROOT?make(fixture):undefined;
    await assert.rejects(vault.refresh());assert.equal(vault.snapshot().catalog,undefined);assert.equal(vault.snapshot().accountId,undefined);
  }
});

test('a forged upload receipt never becomes a confirmed save',async t=>{
  const fixture=server(),real=fixture.fetch;
  const transport=async(path,options)=>{
    const result=await real(path,options);if(options.method!=='PUT')return result;
    const value=await result.json();value.object.sha256=Buffer.alloc(32,5).toString('base64url');return response(value,201);
  };
  const vault=new DocumentVault(transport);t.after(()=>vault.close());await vault.connect();
  await assert.rejects(vault.save(bytes),{code:'INVALID_RESPONSE'});assert.equal(vault.snapshot().phase,'unavailable');assert.equal(vault.snapshot().pendingSave,true);
});

test('a preview is removed when its retained payload expires',async t=>{
  const {vault}=create(t);await vault.connect();const row=await vault.save(bytes,500);await vault.open(row.objectId);
  assert.ok(vault.snapshot().document);await new Promise(resolve=>setTimeout(resolve,600));assert.equal(vault.snapshot().document,undefined);
});

test('a late initial identity cannot repopulate a closed vault',async t=>{
  const fixture=server(),{vault,state}=create(t,fixture),entered=deferred(),release=deferred();
  state.intercept=async path=>{if(path==='/api/me'){entered.resolve();await release.promise;}};
  const pending=vault.connect();await entered.promise;vault.close();release.resolve();await assert.rejects(pending);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(vault.snapshot().accountId,undefined);assert.equal(vault.snapshot().phase,'closed');
});

test('a local clock jump cannot change the server-derived preview deadline',async t=>{
  const {vault,state}=create(t);await vault.connect();const row=await vault.save(bytes);const now=Date.now();
  state.intercept=path=>{if(path===ROOT+'/'+row.objectId)t.mock.method(Date,'now',()=>now+86400000);};
  assert.deepEqual((await vault.open(row.objectId)).document,document);
});
