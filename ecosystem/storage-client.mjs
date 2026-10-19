import {decodeDocument,sha256,MAX_BYTES} from './document-exchange.mjs';
const fail=()=>{throw new Error('STORAGE_EXCHANGE_REJECTED');};
const exact=(v,keys)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.getPrototypeOf(v)===Object.prototype
  &&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const base64=bytes=>btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
function unpack(value,max) {
  if(typeof value!=='string'||value.length>Math.ceil(max/3)*4||!/^[A-Za-z0-9_-]+$/.test(value))fail();
  try {const bytes=Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
    if(bytes.length>max||base64(bytes)!==value)fail();return bytes;
  } catch {fail();}
}
function key(value) { if(unpack(value,32).length!==32)fail();return value; }
const digestKey=async bytes=>base64(Uint8Array.from((await sha256(bytes)).match(/../g),v=>parseInt(v,16)));
// Pure request construction. The caller uses its own same-origin session/CSRF;
// this module accepts no account selector, cookie, bearer credential or URL.
export async function storagePutRequest(input,objectId,retentionMs=60000) {
  key(objectId);
  if(!(input instanceof Uint8Array)||input.length>MAX_BYTES||!Number.isSafeInteger(retentionMs)||retentionMs<1||retentionMs>86400000)fail();
  const bytes=Uint8Array.from(input);await decodeDocument(bytes);
  return Object.freeze({payload:base64(bytes),retentionMs});
}
export async function decodeStoredDocument(response,expected) {
  try {
    if(!exact(expected,['objectId','sha256']))fail();
    const pin={objectId:key(expected.objectId),sha256:key(expected.sha256)};
    if(!exact(response,['schema','mode','account1','accountActive','canOpenContact','operativeAuthority','object'])
      ||response.schema!=='RIO_CMV_SYNTHETIC_OBJECT_V1'||response.mode!=='SYNTHETIC_ONLY'||response.account1!=='HOLD'
      ||response.accountActive!==false||response.canOpenContact!==false||response.operativeAuthority!=='NONE'
      ||!exact(response.object,['objectId','payload','sha256','bytes']))fail();
    const object={...response.object};
    if(object.objectId!==pin.objectId||object.sha256!==pin.sha256)fail();
    const bytes=unpack(object.payload,MAX_BYTES);
    if(object.bytes!==bytes.length||await digestKey(bytes)!==pin.sha256)fail();
    return await decodeDocument(bytes);
  } catch {fail();}
}
