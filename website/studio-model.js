(function(root){
'use strict';
const SCHEMA='PALACO-CX-001/0.2';
const roles=['citadel','cover','illustration','source','watermark-reference'];
const clone=value=>JSON.parse(JSON.stringify(value));
const fail=message=>{throw new Error(message)};
async function digest(value){
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value)));
  return Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
}
function withoutDigest(value){const copy=clone(value);delete copy.digest;return copy}
const text=(value,max)=>typeof value==='string'&&value.length<=max;
const reference=value=>typeof value==='string'&&/^(DOC|BLK|PALACO-ID)-[a-zA-Z0-9-]{1,100}$/.test(value);
const timestamp=value=>text(value,40)&&Number.isFinite(Date.parse(value));
const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
function fields(object,allowed){
  if(!object||typeof object!=='object'||Array.isArray(object))fail('Expected an object.');
  if(Object.keys(object).some(key=>!allowed.includes(key)))fail('Unsupported document fields.');
}
function imageData(value){return text(value,2100000)&&/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)}
function validateDocument(doc){
  fields(doc,['id','title','purpose','citadel','visibility','template','status','verification','authority','creatorId','editorId','revision','createdAt','updatedAt','blocks','digest','parentDigest','importedFrom','restoredFrom']);
  if(!reference(doc.id)||!doc.id.startsWith('DOC-')||!text(doc.title,200)||!text(doc.purpose,4000)||!text(doc.citadel,120))fail('Invalid document metadata.');
  if(!['PRIVATE','SHARED','PUBLIC'].includes(doc.visibility)||!['blank','citadel','proof'].includes(doc.template))fail('Unsupported document settings.');
  if(doc.status!=='LOCAL_DRAFT'||doc.verification!=='UNVERIFIED'||doc.authority!=='NONE')fail('Only local, unverified documents without authority can be imported.');
  if(doc.creatorId!==null&&(!reference(doc.creatorId)||!doc.creatorId.startsWith('PALACO-ID-')))fail('Invalid creator reference.');
  if(doc.editorId!==undefined&&doc.editorId!==null&&(!reference(doc.editorId)||!doc.editorId.startsWith('PALACO-ID-')))fail('Invalid editor reference.');
  if(!Number.isSafeInteger(doc.revision)||doc.revision<0||!timestamp(doc.createdAt)||!timestamp(doc.updatedAt))fail('Invalid revision metadata.');
  if(doc.digest!==undefined&&!hash(doc.digest))fail('Invalid document digest.');
  if(doc.parentDigest!==undefined&&doc.parentDigest!==null&&!hash(doc.parentDigest))fail('Invalid parent digest.');
  if(doc.restoredFrom!==undefined){fields(doc.restoredFrom,['revision','digest']);if(!Number.isSafeInteger(doc.restoredFrom.revision)||doc.restoredFrom.revision<1||!hash(doc.restoredFrom.digest))fail('Invalid restoration reference.')}
  if(doc.importedFrom!==undefined){fields(doc.importedFrom,['documentId','revision','digest','at']);if(!reference(doc.importedFrom.documentId)||!Number.isSafeInteger(doc.importedFrom.revision)||doc.importedFrom.revision<0||!hash(doc.importedFrom.digest)||!timestamp(doc.importedFrom.at))fail('Invalid import reference.')}
  if(!Array.isArray(doc.blocks)||doc.blocks.length>100)fail('Use at most 100 blocks.');
  const ids=new Set();
  for(const block of doc.blocks){
    fields(block,['id','type','at','text','data','name','role','caption','source','verification']);
    if(!reference(block.id)||!block.id.startsWith('BLK-')||ids.has(block.id)||!timestamp(block.at))fail('Invalid or duplicate block reference.');ids.add(block.id);
    if(!['heading','text','image','provenance','divider'].includes(block.type))fail('Unsupported block type.');
    if(['heading','text'].includes(block.type)&&!text(block.text,20000))fail('Invalid block text.');
    if(block.type==='image'&&(!imageData(block.data)||!roles.includes(block.role)||!text(block.name,240)||!text(block.caption,160)||!text(block.source,240)||block.verification!=='UNVERIFIED'))fail('Only local PNG, JPEG or WebP images with unverified metadata are supported.');
  }
  return clone(doc);
}
async function prepareRevision(current,previous,editorId=null){
  const next=withoutDigest(validateDocument(current));next.revision=previous?previous.revision+1:1;
  next.editorId=editorId;validateDocument(next);
  next.parentDigest=previous?previous.digest:null;next.updatedAt=new Date().toISOString();next.digest=await digest(next);return next;
}
async function makeExport(current,identity,pending){
  const doc=withoutDigest(validateDocument(current));doc.digest=await digest(doc);
  const payload={schema:SCHEMA,exportedAt:new Date().toISOString(),boundary:'LOCAL EXPORT — NOT VERIFIED — NO AUTHORITY',pendingChanges:!!pending,identity:identity?clone(identity):null,document:doc};
  payload.exportDigest=await digest(payload);if(new TextEncoder().encode(JSON.stringify(payload,null,2)).byteLength>8000000)fail('This export exceeds 8 MB. Use fewer or smaller images or less text.');return payload;
}
async function readExport(raw){
  if(!text(raw,8000000)||new TextEncoder().encode(raw).byteLength>8000000)fail('Use a PALACO JSON file smaller than 8 MB.');let payload;
  try{payload=JSON.parse(raw)}catch{fail('This file is not valid JSON.')}
  fields(payload,['schema','exportedAt','boundary','pendingChanges','identity','document','exportDigest']);
  if(!['PALACO-CX-001/0.1',SCHEMA].includes(payload.schema)||!timestamp(payload.exportedAt)||!hash(payload.exportDigest))fail('Unsupported PALACO export.');
  const unsigned=clone(payload);delete unsigned.exportDigest;
  if(await digest(unsigned)!==payload.exportDigest)fail('Export digest mismatch. The file was changed.');
  const doc=validateDocument(payload.document);
  if(doc.digest&&await digest(withoutDigest(doc))!==doc.digest)fail('Document digest mismatch. The file was changed or exported with a stale digest.');return doc;
}
async function forkImport(doc){
  const copy=withoutDigest(validateDocument(doc)),sourceDigest=doc.digest||await digest(withoutDigest(doc));
  copy.id='DOC-'+crypto.randomUUID();copy.revision=0;copy.parentDigest=null;copy.editorId=null;copy.createdAt=copy.updatedAt=new Date().toISOString();
  copy.importedFrom={documentId:doc.id,revision:doc.revision,digest:sourceDigest,at:copy.createdAt};delete copy.restoredFrom;return copy;
}
root.PalacoDocuments={SCHEMA,roles,clone,digest,withoutDigest,imageData,validateDocument,prepareRevision,makeExport,readExport,forkImport};
})(globalThis);
