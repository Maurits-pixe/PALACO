import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const code=await readFile(new URL('../studio.js',import.meta.url),'utf8');
const model=await readFile(new URL('../studio-model.js',import.meta.url),'utf8');

// A minimal DOM adapter runs the real workspace controller and event handlers.
// It checks state and persistence, not layout or browser compatibility.
function workspace(initial){
  const nodes=new Map(),listeners={},windows={};let saved=initial||null,quota=false;
  const node=key=>{
    if(!nodes.has(key))nodes.set(key,{value:key==='#title'?'Untitled document':key==='#visibility'?'PRIVATE':'',textContent:'',innerHTML:'',dataset:{},classList:{toggle(){}},focus(){},reset(){},setAttribute(){},removeAttribute(){},addEventListener(type,fn){this[type]=fn},elements:{name:{},alias:{},purpose:{}}});
    return nodes.get(key);
  };
  const context=vm.createContext({PalacoDocuments:null,crypto:globalThis.crypto,TextEncoder,Date,JSON,Array,Set,Error,Number,String,Uint8Array,FormData:class{constructor(form){this.data=form.data||{}}get(key){return this.data[key]}},
    document:{querySelector:node,querySelectorAll:()=>[],addEventListener(type,fn){listeners[type]=fn}},
    window:{addEventListener(type,fn){windows[type]=fn}},localStorage:{getItem:()=>saved,setItem:(key,value)=>{if(quota)throw Error('quota');saved=value}},confirm:()=>true});
  vm.runInContext(model,context);vm.runInContext(code,context);
  const settle=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setTimeout(resolve,5))};
  const click=async(selector,dataset)=>{const target={dataset,closest:s=>s===selector?target:null};listeners.click({target,preventDefault(){}});await settle()};
  const input=async(key,value)=>{const target=node('#'+key);target.value=value;target.input();await settle()};
  const identity=async name=>{node('#identity-form').data={name};node('#identity-form').submit({preventDefault(){},currentTarget:node('#identity-form')});await settle()};
  return {node,click,input,identity,storage:()=>JSON.parse(saved),raw:()=>saved,quota:()=>{quota=true},windows};
}
test('workspace retains saved snapshots when restored content is saved',async()=>{
  const w=workspace();await w.input('title','First');await w.click('[data-action]',{action:'save'});
  await w.input('title','Second');await w.click('[data-action]',{action:'save'});
  const doc=w.storage().docs[0];assert.equal(w.storage().revisions[doc.id].length,2);
  await w.click('[data-restore]',{restore:'1'});assert.equal(w.node('#title').value,'First');assert.match(w.node('#doc-state').textContent,/UNSAVED/);
  await w.click('[data-action]',{action:'save'});const data=w.storage();assert.equal(data.docs[0].revision,3);assert.equal(data.revisions[doc.id][1].title,'Second');
});
test('failed storage does not advance saved revision or report success',async()=>{
  const w=workspace();await w.input('title','Saved');await w.click('[data-action]',{action:'save'});const prior=w.raw();
  w.quota();await w.input('title','Still open');await w.click('[data-action]',{action:'save'});
  assert.equal(w.raw(),prior);assert.match(w.node('#workspace-message').textContent,/Saving failed/);assert.match(w.node('#doc-state').textContent,/UNSAVED/);assert.equal(w.node('#title').value,'Still open');
});
test('a replacement ID does not reassign an existing document creator',async()=>{
  const w=workspace();await w.identity('Original');await w.click('[data-action]',{action:'save'});const creator=w.storage().docs[0].creatorId;
  await w.click('[data-action]',{action:'delete-id'});await w.identity('Replacement');assert.notEqual(w.storage().identity.palacoId,creator);
  await w.input('title','Edited');await w.click('[data-action]',{action:'save'});assert.equal(w.storage().docs[0].creatorId,creator);assert.equal(w.storage().docs[0].editorId,w.storage().identity.palacoId);
});
test('opening a saved document never edits its stored copy before save',async()=>{
  const w=workspace();await w.input('title','First');await w.click('[data-action]',{action:'save'});const key=w.storage().docs[0].id;
  await w.click('[data-open]',{open:key});await w.input('title','Unsaved');assert.equal(w.storage().docs[0].title,'First');assert.match(w.node('#digest').textContent,/CHANGED/);
});
test('legacy documents migrate using only their available revision',async()=>{
  const first=workspace();await first.input('title','Legacy');await first.click('[data-action]',{action:'save'});const data=first.storage();delete data.revisions;
  const w=workspace(JSON.stringify(data));await w.input('title','Next');await w.click('[data-action]',{action:'save'});
  assert.equal(w.storage().docs[0].revision,2);assert.equal(w.storage().revisions[data.docs[0].id][0].title,'Legacy');
});
test('another tab cannot silently overwrite a local workspace',async()=>{
  const w=workspace();await w.input('title','First');await w.click('[data-action]',{action:'save'});const prior=w.raw();
  w.windows.storage({key:'palaco-cx001'});await w.input('title','Second');await w.click('[data-action]',{action:'save'});assert.equal(w.raw(),prior);assert.match(w.node('#workspace-message').textContent,/protected/);
});
