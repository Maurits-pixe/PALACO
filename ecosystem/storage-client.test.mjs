import test from 'node:test';import assert from 'node:assert/strict';
import {encodeDocument,sha256} from './document-exchange.mjs';
import {storagePutRequest,decodeStoredDocument} from './storage-client.mjs';
const id='A'.repeat(43),ref={repository:'Maurits-pixe/PALACO',commitSha:'a'.repeat(40),path:'README.md'};
const doc={documentId:'storage-fixture',title:'Fixture',content:'Synthetic stored exchange.',status:'draft'};
const b64=bytes=>Buffer.from(bytes).toString('base64url');
test('request and pinned storage response round-trip canonical packet bytes',async()=>{
 const bytes=await encodeDocument(ref,doc),body=await storagePutRequest(bytes,id);
 const digest=b64(Buffer.from(await sha256(bytes),'hex'));
 const response={schema:'RIO_CMV_SYNTHETIC_OBJECT_V1',mode:'SYNTHETIC_ONLY',account1:'HOLD',accountActive:false,
   canOpenContact:false,operativeAuthority:'NONE',object:{objectId:id,payload:body.payload,sha256:digest,bytes:bytes.length}};
 assert.deepEqual((await decodeStoredDocument(response,{objectId:id,sha256:digest})).document,doc);
 for(const altered of [{...response,accountActive:true},{...response,ownerId:'other'},
   {...response,object:{...response.object,bytes:0}}, {...response,object:{...response.object,payload:body.payload+'='}}])
   await assert.rejects(decodeStoredDocument(altered,{objectId:id,sha256:digest}));
 await assert.rejects(decodeStoredDocument(response,{objectId:id,sha256:id}));
 await assert.rejects(decodeStoredDocument(response,{objectId:'B'.repeat(43),sha256:digest}));
});
test('invalid packets, IDs and retention never become storage requests',async()=>{
 const bytes=await encodeDocument(ref,doc);
 for(const ttl of [0,86400001,1.5,'60000',null]) await assert.rejects(storagePutRequest(bytes,id,ttl));
 await assert.rejects(storagePutRequest(bytes,'short'));await assert.rejects(storagePutRequest(new Uint8Array([0xff]),id));
});
