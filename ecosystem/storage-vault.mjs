import {decodeDocument,sha256,MAX_BYTES} from './document-exchange.mjs';
import {storagePutRequest,decodeStoredDocument} from './storage-client.mjs';

const ROOT='/api/storage/objects';
const LIMITS=Object.freeze({objectBytes:16384,liveBytes:65536,lifetimeObjects:64,retentionMs:86400000});
const exact=(v,keys)=>v!==null&&typeof v==='object'&&!Array.isArray(v)
  &&Object.getPrototypeOf(v)===Object.prototype&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const integer=(v,min=0,max=Number.MAX_SAFE_INTEGER)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
const frozen=v=>{for(const x of Object.values(v))if(x&&typeof x==='object')frozen(x);return Object.freeze(v);};
const b64=bytes=>btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
const key=v=>{
  if(typeof v!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(v))return false;
  try{return b64(Uint8Array.from(atob(v.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0)))===v;}catch{return false;}
};
const boundary=v=>v.mode==='SYNTHETIC_ONLY'&&v.account1==='HOLD'&&v.accountActive===false
  &&v.canOpenContact===false&&v.operativeAuthority==='NONE';
const common=['schema','mode','account1','accountActive','canOpenContact','operativeAuthority'];
export class VaultError extends Error {constructor(code){super(code);this.name='VaultError';this.code=code;}}
const reject=()=>{throw new VaultError('INVALID_RESPONSE');};
const usage=v=>exact(v,['liveBytes','retainedObjects'])&&integer(v.liveBytes,0,LIMITS.liveBytes)
  &&integer(v.retainedObjects,0,LIMITS.lifetimeObjects);
function me(v){
  if(!exact(v,['accountId','csrfToken','actorKind','credentialControl','accountActive','mode','operativeAuthority','canOpenContact','account1'])
    ||!boundary(v)||!['TST-alpha','TST-beta'].includes(v.accountId)||!key(v.csrfToken)
    ||v.actorKind!=='SYNTHETIC_DEV_ACTOR'||v.credentialControl!=='VERIFIED_DEV_OIDC')reject();
  return {accountId:v.accountId,csrf:v.csrfToken};
}
export function validateCatalog(v){
  if(!exact(v,[...common,'observedAt','objects','usage'])||!boundary(v)||v.schema!=='RIO_CMV_SYNTHETIC_CATALOG_V1'
    ||!integer(v.observedAt)||!Array.isArray(v.objects)||v.objects.length>64||!usage(v.usage)
    ||v.usage.retainedObjects!==v.objects.length)reject();
  const ids=new Set();let liveBytes=0;
  const objects=v.objects.map(row=>{
    if(!exact(row,['objectId','sha256','liveBytes','state','createdAt','expiresAt','endedAt','payloadVerified'])
      ||!key(row.objectId)||!key(row.sha256)||ids.has(row.objectId)||!integer(row.createdAt,0,v.observedAt)
      ||!integer(row.expiresAt,row.createdAt+1)||row.expiresAt-row.createdAt>LIMITS.retentionMs)reject();
    ids.add(row.objectId);
    if(row.state==='LIVE'){
      if(!integer(row.liveBytes,1,MAX_BYTES)||row.endedAt!==null||row.payloadVerified!==true||row.expiresAt<=v.observedAt)reject();
      liveBytes+=row.liveBytes;
    }else{
      if(!['DELETED','EXPIRED'].includes(row.state)||row.liveBytes!==0||row.payloadVerified!==false
        ||!integer(row.endedAt,row.createdAt,v.observedAt)
        ||(row.state==='DELETED'?row.endedAt>=row.expiresAt:row.endedAt<row.expiresAt))reject();
    }
    return {...row};
  });
  if(liveBytes!==v.usage.liveBytes)reject();
  return frozen({observedAt:v.observedAt,objects,usage:{...v.usage},limits:{...LIMITS}});
}
function validateLimits(v){
  if(!exact(v,[...common,'usage','limits'])||!boundary(v)||v.schema!=='RIO_CMV_SYNTHETIC_OBJECT_V1'
    ||!usage(v.usage)||!exact(v.limits,Object.keys(LIMITS))||Object.keys(LIMITS).some(k=>v.limits[k]!==LIMITS[k]))reject();
}

// Fixed same-origin endpoints, memory-only state, no account or URL parameters.
// The fetch dependency is injected only by tests; the page uses the browser fetch.
export class DocumentVault {
  #fetch;#notify;#epoch=0;#controllers=new Set();#session;#catalog;#catalogStarted;#document;#pending;#expiry;
  #phase='closed';#busy=false;
  constructor(fetcher=globalThis.fetch.bind(globalThis),notify=()=>{}){this.#fetch=fetcher;this.#notify=notify;}
  snapshot(){return Object.freeze({phase:this.#phase,busy:this.#busy,accountId:this.#session?.accountId,
    catalog:this.#catalog,document:this.#document,pendingSave:!!this.#pending});}
  #emit(){try{this.#notify(this.snapshot());}catch{}}
  #reset(phase,keepPending=false){
    this.#epoch++;for(const c of this.#controllers)c.abort();this.#controllers.clear();clearTimeout(this.#expiry);
    this.#session=undefined;this.#catalog=undefined;this.#catalogStarted=undefined;this.#document=undefined;this.#busy=phase==='logging-out';this.#phase=phase;
    if(!keepPending)this.#pending=undefined;this.#emit();
  }
  close(){this.#reset('closed');}
  #current(epoch){if(epoch!==this.#epoch)throw new VaultError('CLOSED');}
  async #request(path,epoch,method='GET',body,csrf){
    this.#current(epoch);
    const controller=new AbortController();this.#controllers.add(controller);let reader;
    const cancelled=new Promise((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new VaultError('UNAVAILABLE')),{once:true}));
    const timer=setTimeout(()=>controller.abort(),8000);
    const operation=(async()=>{
      const response=await this.#fetch(path,{method,credentials:'same-origin',cache:'no-store',redirect:'error',
        signal:controller.signal,headers:body===undefined?{accept:'application/json'}:
          {accept:'application/json','content-type':'application/json','x-csrf-token':csrf},
        ...(body===undefined?{}:{body:JSON.stringify(body)})});
      this.#current(epoch);
      if(!response.ok){void response.body?.cancel().catch(()=>{});
        throw new VaultError([401,403].includes(response.status)?'AUTHENTICATION_REQUIRED':response.status===409?'CONFLICT':'UNAVAILABLE');}
      if(response.status!==200&&!(method==='PUT'&&response.status===201))reject();
      if((response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase()!=='application/json'||!response.body)reject();
      const length=response.headers.get('content-length');
      if(length!==null&&(!/^\d+$/.test(length)||Number(length)>40000))reject();
      reader=response.body.getReader();let size=0;const chunks=[];
      while(true){const part=await reader.read();this.#current(epoch);if(part.done)break;
        size+=part.value.byteLength;if(size>40000)reject();chunks.push(part.value);}
      const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      const value=JSON.parse(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes));
      return {status:response.status,value};
    })();
    try{return await Promise.race([operation,cancelled]);}
    catch(error){controller.abort();if(reader)void reader.cancel().catch(()=>{});throw error;}
    finally{clearTimeout(timer);this.#controllers.delete(controller);}
  }
  async #run(action,needsSession=true){
    if(this.#busy)throw new VaultError('BUSY');
    if(needsSession&&this.#phase!=='ready')throw new VaultError('AUTHENTICATION_REQUIRED');
    const epoch=this.#epoch;this.#busy=true;this.#emit();
    try{const result=await action(epoch);this.#current(epoch);return result;}
    catch(error){if(epoch===this.#epoch)this.#reset(error?.code==='AUTHENTICATION_REQUIRED'?'anonymous':'unavailable',error?.code!=='AUTHENTICATION_REQUIRED');
      throw error instanceof VaultError?error:new VaultError('INVALID_RESPONSE');}
    finally{if(epoch===this.#epoch){this.#busy=false;this.#emit();}}
  }
  async #identity(epoch){
    const identity=me((await this.#request('/api/me',epoch)).value);this.#current(epoch);
    if(this.#session&&(identity.accountId!==this.#session.accountId||identity.csrf!==this.#session.csrf))throw new VaultError('AUTHENTICATION_REQUIRED');
    return identity;
  }
  async #list(epoch){
    validateLimits((await this.#request('/api/storage/usage',epoch)).value);
    const started=performance.now(),catalog=validateCatalog((await this.#request(ROOT,epoch)).value);
    await this.#identity(epoch);this.#current(epoch);this.#catalog=catalog;this.#catalogStarted=started;return catalog;
  }
  async connect(){
    this.#reset('checking',true);
    return this.#run(async epoch=>{
      const identity=await this.#identity(epoch);this.#current(epoch);this.#session=identity;
      if(this.#pending?.accountId!==this.#session.accountId)this.#pending=undefined;
      await this.#list(epoch);this.#current(epoch);this.#phase='ready';return this.snapshot();
    },false);
  }
  async check(){if(this.#busy||this.#phase!=='ready')return;return this.#run(epoch=>this.#identity(epoch));}
  async refresh(){return this.#run(async epoch=>{
    this.#document=undefined;clearTimeout(this.#expiry);this.#emit();await this.#identity(epoch);return this.#list(epoch);
  });}
  async save(input,retentionMs=60000){
    if(!(input instanceof Uint8Array)||input.length>MAX_BYTES)throw new VaultError('INVALID_DOCUMENT');
    const bytes=Uint8Array.from(input),epoch=this.#epoch;await decodeDocument(bytes);this.#current(epoch);
    if(!integer(retentionMs,1,LIMITS.retentionMs))throw new VaultError('INVALID_DOCUMENT');
    const digest=b64(Uint8Array.from((await sha256(bytes)).match(/../g),n=>parseInt(n,16)));this.#current(epoch);
    if(this.#pending&&(this.#pending.sha256!==digest||this.#pending.retentionMs!==retentionMs))throw new VaultError('PENDING_SAVE');
    return this.#run(async epoch=>{
      await this.#identity(epoch);this.#current(epoch);
      if(!this.#pending)this.#pending={objectId:b64(crypto.getRandomValues(new Uint8Array(32))),sha256:digest,retentionMs,accountId:this.#session.accountId};
      const pending=this.#pending,body=await storagePutRequest(bytes,pending.objectId,retentionMs);this.#current(epoch);
      const response=await this.#request(ROOT+'/'+pending.objectId,epoch,'PUT',body,this.#session.csrf),v=response.value;
      if(![200,201].includes(response.status)||!exact(v,[...common,'object'])||!boundary(v)||v.schema!=='RIO_CMV_SYNTHETIC_OBJECT_V1'
        ||!exact(v.object,['objectId','sha256','bytes'])||v.object.objectId!==pending.objectId||v.object.sha256!==digest||v.object.bytes!==bytes.length)reject();
      const catalog=await this.#list(epoch),row=catalog.objects.find(r=>r.objectId===pending.objectId);
      if(!row||row.sha256!==digest||row.expiresAt-row.createdAt!==retentionMs||(row.state==='LIVE'&&row.liveBytes!==bytes.length))reject();
      this.#current(epoch);this.#pending=undefined;return row;
    });
  }
  async open(objectId){return this.#run(async epoch=>{
    this.#document=undefined;clearTimeout(this.#expiry);this.#emit();
    const row=this.#catalog.objects.find(r=>r.objectId===objectId&&r.state==='LIVE');if(!row)throw new VaultError('NOT_LIVE');
    await this.#identity(epoch);
    const response=await this.#request(ROOT+'/'+row.objectId,epoch);
    const packet=await decodeStoredDocument(response.value,{objectId:row.objectId,sha256:row.sha256});
    if(response.value.object.bytes!==row.liveBytes)reject();
    await this.#identity(epoch);this.#current(epoch);
    // Use the server observation and elapsed monotonic time. Starting before the
    // catalog request conservatively includes network delay, independent of local clock changes.
    const remaining=row.expiresAt-this.#catalog.observedAt-(performance.now()-this.#catalogStarted);
    if(remaining<=0)throw new VaultError('NOT_LIVE');
    this.#document=packet;this.#expiry=setTimeout(()=>{this.#document=undefined;this.#emit();},Math.min(remaining,86400000));
    return packet;
  });}
  async erase(objectId){return this.#run(async epoch=>{
    this.#document=undefined;clearTimeout(this.#expiry);this.#emit();
    const row=this.#catalog.objects.find(r=>r.objectId===objectId&&r.state==='LIVE');if(!row)throw new VaultError('NOT_LIVE');
    await this.#identity(epoch);
    const {value:v}=await this.#request(ROOT+'/'+row.objectId,epoch,'DELETE',{sha256:row.sha256},this.#session.csrf);
    if(!exact(v,[...common,'object','usage'])||!boundary(v)||v.schema!=='RIO_CMV_SYNTHETIC_OBJECT_V1'||!usage(v.usage)
      ||!exact(v.object,['objectId','state','sha256','endedAt','liveBytes','payloadVerified'])
      ||v.object.objectId!==row.objectId||v.object.sha256!==row.sha256||!['DELETED','EXPIRED'].includes(v.object.state)
      ||v.object.liveBytes!==0||v.object.payloadVerified!==false||!integer(v.object.endedAt,row.createdAt))reject();
    const catalog=await this.#list(epoch),terminal=catalog.objects.find(r=>r.objectId===row.objectId);
    if(!terminal||terminal.sha256!==row.sha256||terminal.state!==v.object.state||terminal.endedAt!==v.object.endedAt)reject();
    return terminal;
  });}
  async logout(){
    const csrf=this.#session?.csrf;this.#reset(csrf?'logging-out':'closed');if(!csrf)return;
    const epoch=this.#epoch;
    try{const {value:v}=await this.#request('/auth/logout',epoch,'POST',{},csrf);
      if(!exact(v,['loggedOut','providerLogout','mode'])||v.loggedOut!==true||v.providerLogout!=='NOT_REQUESTED'||v.mode!=='SYNTHETIC_ONLY')reject();
      this.#current(epoch);this.#busy=false;this.#phase='anonymous';this.#emit();
    }catch(error){if(epoch===this.#epoch)this.#reset('unavailable');throw error instanceof VaultError?error:new VaultError('INVALID_RESPONSE');}
  }
}
