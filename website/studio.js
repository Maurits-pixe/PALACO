(function(){
'use strict';
const M=PalacoDocuments,KEY='palaco-cx001';
const state={identity:null,docs:[],revisions:{},current:null,template:'blank',dirty:false,busy:false,imageId:null,rioContext:null,expectedRaw:null};
const $=(s,r)=>(r||document).querySelector(s),$$=(s,r)=>Array.from((r||document).querySelectorAll(s));
const now=()=>new Date().toISOString(),id=p=>p+'-'+crypto.randomUUID();
const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function busy(value){state.busy=value;$$('#title,#purpose,#citadel,#visibility,[data-edit],#identity-form input,#identity-form textarea').forEach(node=>{node.disabled=value})}
function fitText(node){node.style.height='auto';node.style.height=node.scrollHeight+'px'}
function fitDocument(){requestAnimationFrame(()=>$$('#title,.heading-input,.text-input').forEach(fitText))}
function notice(message,error=false){$('#workspace-message').textContent=message;$('#workspace-message').classList.toggle('error',error)}
async function persist(identity=state.identity,docs=state.docs,revisions=state.revisions){
  if(!navigator.locks){notice('Safe local saving is unavailable in this browser. Export a JSON copy to keep your changes.',true);return false}
  try{return await navigator.locks.request(KEY+'-write',{mode:'exclusive'},()=>{
    if(state.storageBlocked||localStorage.getItem(KEY)!==state.expectedRaw){state.storageBlocked=true;notice('PALACO data changed in another tab. Export your unsaved work, then reload before saving.',true);return false}
    const raw=JSON.stringify({identity,docs,revisions});localStorage.setItem(KEY,raw);state.expectedRaw=raw;return true;
  })}
  catch{notice('Saving failed. Your changes remain open. Export a JSON copy to keep them.',true);return false}
}
function templateBlocks(t){
  if(t==='blank')return [];
  return [{id:id('BLK'),type:'heading',text:t==='citadel'?'Citadel overview':'Evidence note',at:now()},
    {id:id('BLK'),type:'text',text:t==='citadel'?'Purpose, context and boundaries of this Citadel.':'Describe the observation. Keep claim, source and verification state separate.',at:now()},
    {id:id('BLK'),type:'provenance',at:now()}];
}
function newDoc(){return {id:id('DOC'),title:'Untitled document',purpose:'',citadel:'',visibility:'PRIVATE',template:state.template,status:'LOCAL_DRAFT',verification:'UNVERIFIED',authority:'NONE',creatorId:state.identity?state.identity.palacoId:null,revision:0,createdAt:now(),updatedAt:now(),blocks:templateBlocks(state.template)}}
function load(){
  try{
    const raw=localStorage.getItem(KEY);state.expectedRaw=raw;
    if(raw){const value=JSON.parse(raw);state.identity=value.identity||null;state.docs=(value.docs||[]).map(M.validateDocument);
      const histories=value.revisions||{};
      for(const doc of state.docs){const records=histories[doc.id]||[M.clone(doc)];state.revisions[doc.id]=records.map(M.validateDocument)}
    }
  }catch{state.identity=null;state.docs=[];state.revisions={};notice('Local data could not be read. The original storage has been kept.',true);state.storageBlocked=true}
  state.current=M.clone(state.docs.slice().sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt))[0]||newDoc());renderIdentity();renderDoc();
}
function go(view){
  $$('.view').forEach(n=>n.classList.toggle('visible',n.dataset.panel===view));
  $$('.rail button').forEach(n=>{n.classList.toggle('active',n.dataset.view===view);if(n.dataset.view===view)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current')});
  if(view==='docs')renderLibrary();if(view==='proof')renderProof().catch(showError);if(view==='build')renderDoc();$('#main').focus({preventScroll:true});
}
function showError(error){const message=error.message||'The operation could not be completed.';notice(message,true);if($('#image-dialog').open)$('#image-message').textContent=message}
function checkStorage(){if(state.storageBlocked)throw Error('Changed or unreadable local data is protected. Export your unsaved work, then reload before saving.')}
async function saveIdentity(form){
  if(state.busy)return;checkStorage();const f=new FormData(form);busy(true);
  try{
    const base=state.identity||{palacoId:'PALACO-ID-'+crypto.randomUUID(),createdAt:now(),version:'CX-001/0.2'};
    const next={palacoId:base.palacoId,createdAt:base.createdAt,version:base.version,name:(f.get('name')||'').trim()||'Unnamed creator',alias:(f.get('alias')||'').trim(),purpose:(f.get('purpose')||'').trim(),status:'LOCAL_DRAFT',verification:'UNVERIFIED',authority:'NONE',updatedAt:now()};
    next.digest=await M.digest(next);
    if(!await persist(next))return;state.identity=next;
    if(!state.current.creatorId&&state.current.revision===0&&!state.current.importedFrom){state.current.creatorId=next.palacoId;markDirty()}
    renderIdentity();renderDoc();notice('Local ID saved. You can now build your document.');
  }finally{busy(false)}
}
function renderIdentity(){
  const card=$('#identity-card'),form=$('#identity-form');
  if(!state.identity){card.innerHTML='<p class="eyebrow">PALACO · IDENTITY</p><h3>No local ID yet</h3><p>Create one to bind new local documents to a visible creator reference.</p>';form.reset();return}
  const identity=state.identity;form.elements.name.value=identity.name||'';form.elements.alias.value=identity.alias||'';form.elements.purpose.value=identity.purpose||'';
  card.innerHTML='<p class="eyebrow">PALACO · IDENTITY</p><h3>'+esc(identity.name)+'</h3><p>'+esc(identity.purpose||'Local creator identity')+'</p><dl><dt>ID</dt><dd>'+esc(identity.palacoId)+'</dd><dt>Alias</dt><dd>'+esc(identity.alias||'—')+'</dd><dt>Status</dt><dd>LOCAL DRAFT</dd><dt>Verification</dt><dd>UNVERIFIED</dd><dt>Authority</dt><dd>NONE</dd><dt>Digest</dt><dd>'+esc(identity.digest||'—')+'</dd></dl>';
}
function sync(){state.current.title=$('#title').value.trim()||'Untitled document';state.current.purpose=$('#purpose').value.trim();state.current.citadel=$('#citadel').value.trim();state.current.visibility=$('#visibility').value}
function clearContext(){state.rioContext=null;$('#rio-context-state').textContent='No document context attached.'}
function markDirty(){state.dirty=true;$('#doc-state').textContent='UNSAVED CHANGES · REV '+state.current.revision;$('#digest').textContent='CHANGED · SAVE TO HASH';clearContext()}
async function saveDoc(){
  if(state.busy)return;checkStorage();sync();busy(true);
  try{
    const captured=M.clone(state.current),before=JSON.stringify(captured),previous=state.docs.find(d=>d.id===captured.id);
    if(previous&&!state.dirty){notice('This revision is already saved.');return}
    const next=await M.prepareRevision(captured,previous,state.identity?state.identity.palacoId:null);
    const docs=state.docs.filter(d=>d.id!==next.id).concat(next),revisions={...state.revisions,[next.id]:(state.revisions[next.id]||[]).concat(M.clone(next))};
    if(!await persist(state.identity,docs,revisions))return;state.docs=docs;state.revisions=revisions;
    if(state.current.id===next.id){
      if(JSON.stringify(state.current)===before){state.current=M.clone(next);state.dirty=false}
      else{state.current.revision=next.revision;state.current.digest=next.digest;state.dirty=true}
      renderDoc();
    }
    clearContext();renderLibrary();notice('Revision '+next.revision+' saved in this browser.');
  }finally{busy(false)}
}
function discardAllowed(){return !state.dirty||confirm('Leave the unsaved changes? Save or export first to keep them.')}
function openImage(block){
  state.imageId=block?block.id:null;$('#image-form').reset();$('#image-message').textContent='';$('#image-file').setCustomValidity('');$('#image-file').required=!block;$('#image-file-label').hidden=!!block;
  $('#image-role').value=block?block.role:'citadel';$('#image-caption').value=block?block.caption:'';$('#image-source').value=block?block.source:'';
  $('#image-submit').textContent=block?'Apply image details':'Insert image';$('#image-dialog').showModal();
}
function addBlock(type){
  if(type==='image'){openImage();return}if(state.current.blocks.length>=100)throw Error('Use at most 100 blocks.');
  const block={id:id('BLK'),type,at:now()};if(type==='heading')block.text='New heading';if(type==='text')block.text='Write here…';state.current.blocks.push(block);markDirty();renderDoc();
}
const fileAsDataUrl=file=>new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('The image could not be read.'));r.readAsDataURL(file)});
async function decodedImage(blob){const bitmap=await createImageBitmap(blob);const valid=bitmap.width<=8192&&bitmap.height<=8192;bitmap.close();if(!valid)throw Error('Use an image at most 8192 pixels wide and high.')}
async function insertImage(){
  if(state.busy)return;const currentId=state.current.id,editId=state.imageId;
  const details={role:$('#image-role').value,caption:$('#image-caption').value.trim(),source:$('#image-source').value.trim()};
  if(editId){const block=state.current.blocks.find(b=>b.id===editId);if(block){Object.assign(block,details);markDirty();renderDoc();$('#image-dialog').close()}return}
  const input=$('#image-file'),file=input.files&&input.files[0];if(!file){input.setCustomValidity('Choose an image first.');input.reportValidity();return}
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>1500000)throw Error('Choose a PNG, JPEG or WebP image smaller than 1.5 MB.');
  if(state.current.blocks.length>=100)throw Error('Use at most 100 blocks.');busy(true);
  try{
    await decodedImage(file);const data=await fileAsDataUrl(file);if(!M.imageData(data))throw Error('Unsupported image data.');if(state.current.id!==currentId)throw Error('The document changed. Add the image again.');
    state.current.blocks.push({id:id('BLK'),type:'image',data,name:file.name.slice(0,240),...details,verification:'UNVERIFIED',at:now()});markDirty();$('#image-dialog').close();renderDoc();notice('Image added. Its source and role remain editable.');
  }finally{busy(false)}
}
function controls(block){return '<div class="block-actions"><button data-block="up" data-id="'+esc(block.id)+'" aria-label="Move block up">↑</button><button data-block="down" data-id="'+esc(block.id)+'" aria-label="Move block down">↓</button><button data-block="delete" data-id="'+esc(block.id)+'" aria-label="Remove block">×</button></div>'}
function renderDoc(){
  const doc=state.current;$('#title').value=doc.title;$('#purpose').value=doc.purpose;$('#citadel').value=doc.citadel;$('#visibility').value=doc.visibility;
  $('#sheet-owner').textContent=state.identity&&state.identity.palacoId===doc.creatorId?state.identity.name:(doc.creatorId||'NO ID');$('#sheet-id').textContent=doc.id;$('#creator').textContent=doc.creatorId||'NO ID';$('#editor').textContent=doc.editorId||'NO ID';
  $('#digest').textContent=state.dirty?'CHANGED · SAVE TO HASH':doc.digest?doc.digest.slice(0,24)+'…':'NOT HASHED';$('#doc-state').textContent=(state.dirty?'UNSAVED CHANGES':doc.revision?'SAVED LOCAL':'UNSAVED')+' · REV '+doc.revision;
  $$('[data-template]').forEach(n=>n.classList.toggle('selected',n.dataset.template===doc.template));
  $('#blocks').innerHTML=doc.blocks.length?doc.blocks.map(block=>{
    let inner='';const key=esc(block.id);
    if(block.type==='heading')inner='<textarea class="heading-input" rows="1" maxlength="20000" aria-label="Heading text" data-edit="'+key+'">'+esc(block.text)+'</textarea>';
    if(block.type==='text')inner='<textarea class="text-input" maxlength="20000" aria-label="Paragraph text" data-edit="'+key+'">'+esc(block.text)+'</textarea>';
    if(block.type==='divider')inner='<div class="divider"></div>';
    if(block.type==='provenance')inner='<div class="prov"><div><span class="eyebrow">CREATOR</span><b>'+esc(doc.creatorId||'NO ID')+'</b></div><div><span class="eyebrow">STATUS</span><b>LOCAL DRAFT</b></div><div><span class="eyebrow">VERIFICATION</span><b>UNVERIFIED</b></div><div><span class="eyebrow">CITADEL</span><b>'+esc(doc.citadel||'—')+'</b></div></div>';
    if(block.type==='image')inner='<figure><img class="image-'+esc(block.role)+'" src="'+esc(block.data)+'" alt="'+esc(block.caption||block.role)+'"><figcaption><span>'+esc(block.caption||block.name)+'</span><span class="role">'+esc(block.role)+'</span></figcaption><p class="boundary">Source: '+esc(block.source||'not supplied')+' · UNVERIFIED</p><button class="image-details" data-image-edit="'+key+'">Use this image as… / Edit details</button></figure>';
    return '<section class="block '+(block.type==='image'?'image-block':'')+'" data-block-id="'+key+'">'+inner+controls(block)+'</section>';
  }).join(''):'<div class="empty"><p class="eyebrow">BLANK TEMPLATE</p><p>Add a heading, text, image, provenance card or divider.</p></div>';renderHistory();fitDocument();
}
function move(key,action){
  const index=state.current.blocks.findIndex(block=>block.id===key);if(index<0)return;
  if(action==='delete')state.current.blocks.splice(index,1);else{const target=index+(action==='up'?-1:1);if(target<0||target>=state.current.blocks.length)return;[state.current.blocks[index],state.current.blocks[target]]=[state.current.blocks[target],state.current.blocks[index]]}markDirty();renderDoc();
}
function renderHistory(){const records=state.revisions[state.current.id]||[];$('#revision-history').innerHTML=records.length?records.slice().reverse().map(record=>'<li><span>Revision '+record.revision+' · '+esc(record.updatedAt)+'</span><button data-restore="'+record.revision+'">Restore as draft</button></li>').join(''):'<li>No saved revisions yet.</li>'}
function restoreRevision(revision){
  if(!discardAllowed())return;const saved=(state.revisions[state.current.id]||[]).find(record=>record.revision===Number(revision));if(!saved)return;
  const latest=state.docs.find(doc=>doc.id===saved.id);state.current=M.clone(saved);state.current.revision=latest.revision;state.current.digest=latest.digest;
  state.current.restoredFrom={revision:saved.revision,digest:saved.digest};markDirty();renderDoc();notice('Earlier content restored as a draft. Save to create a new revision.');
}
function renderLibrary(){
  $('#library').innerHTML=state.docs.length?state.docs.slice().sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).map(doc=>'<article class="card"><p class="eyebrow">'+esc(doc.template)+' · REV '+doc.revision+'</p><h3>'+esc(doc.title)+'</h3><p>'+esc(doc.purpose||'No purpose supplied.')+'</p><p class="boundary">'+esc(doc.id)+' · '+esc(doc.visibility)+' INTENT · UNVERIFIED</p><div class="row"><button data-open="'+esc(doc.id)+'">Open</button><button data-delete="'+esc(doc.id)+'">Delete</button></div></article>').join(''):'<article class="panel"><h3>No saved documents yet</h3><p>Build your first document and save a revision.</p></article>';
}
async function renderProof(){
  sync();const identity=state.identity,doc=M.clone(state.current),pending=state.dirty;
  $('#proof-id').innerHTML=identity?'<p><b>'+esc(identity.name)+'</b></p><p>'+esc(identity.palacoId)+'</p><p>LOCAL DRAFT · UNVERIFIED · AUTHORITY NONE</p><code>'+esc(identity.digest)+'</code>':'<p>No local identity.</p>';
  const computed=await M.digest(M.withoutDigest(doc));if(state.current.id!==doc.id)return;
  $('#proof-doc').innerHTML='<p><b>'+esc(doc.title)+'</b></p><p>'+esc(doc.id)+' · REV '+doc.revision+'</p><p>LOCAL DRAFT · UNVERIFIED · AUTHORITY NONE</p><p>'+(pending?'Unsaved working content.':'Current local content.')+'</p><code>'+computed+'</code><p>Saved digest: '+esc(doc.digest||'none')+'</p>';
  if(doc.importedFrom)$('#proof-doc').innerHTML+='<p>Imported source reference (unverified): '+esc(doc.importedFrom.documentId)+'</p>';
}
async function exportDoc(){
  sync();const payload=await M.makeExport(state.current,state.identity,state.dirty),url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'})),anchor=document.createElement('a');anchor.href=url;
  anchor.download=(payload.document.title||'palaco-document').toLowerCase().replace(/[^a-z0-9]+/g,'-')+'.palaco.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('JSON exported with the current content and local change-detection digests.');
}
async function importDoc(file){
  if(!file||state.busy)return;if(file.size>8000000)throw Error('Use a PALACO JSON file smaller than 8 MB.');if(!discardAllowed())return;busy(true);
  try{
    const imported=await M.readExport(await file.text()),fork=await M.forkImport(imported);
    for(const block of fork.blocks.filter(block=>block.type==='image')){const binary=atob(block.data.split(',')[1]),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));await decodedImage(new Blob([bytes]))}
    state.current=fork;state.template=fork.template;markDirty();renderDoc();go('build');notice('Imported as a new local draft. The source creator stays visible; your ID is unchanged. Save to keep this copy.');
  }finally{busy(false);$('#import-file').value=''}
}
function rio(question){
  const q=question.toLowerCase();
  if(q.includes('image')||q.includes('foto'))return 'Build → Image. Choose a file and its role. Use “Edit details” to change the role, caption or source later. A role never verifies an image.';
  if(q.includes('import')||q.includes('open file'))return 'Docs → Import JSON. A matching export digest detects changes. Imports become new local drafts and never replace your ID or gain authority.';
  if(q.includes('revision')||q.includes('revisie')||q.includes('restore'))return 'Build → Revision history. Restore earlier content as a draft, then save a new revision. Previous snapshots are retained.';
  if(q.includes('id'))return 'Open ID. Create a local creator reference. It remains LOCAL DRAFT, UNVERIFIED and AUTHORITY NONE.';
  if(q.includes('provenance')||q.includes('proof'))return 'PALACO keeps creator, source, status, Citadel reference, revision and digest visible. A digest detects change and does not establish trust or authority.';
  if(q.includes('export')||q.includes('save'))return 'Save keeps a local snapshot in this browser. Export copies the current content into a .palaco.json package. Visibility records intent and does not share the document.';
  if(state.rioContext)return 'Attached local context: '+state.rioContext+'. You can add a heading, text, image or provenance card. This is deterministic guidance; no data is sent to a provider.';
  return 'I can guide identity, building, images, revisions, importing, provenance and export. Attach your document summary for local guidance. Live RIO intelligence is not connected.';
}
function rioMsg(who,message){const article=document.createElement('article');article.className=who==='YOU'?'rio-user':'rio-system';article.innerHTML='<b>'+esc(who)+'</b><p>'+esc(message)+'</p>';$('#rio-log').appendChild(article);article.scrollIntoView({block:'end'})}
function attachContext(){sync();const doc=state.current;state.rioContext=doc.title+' · '+doc.blocks.length+' blocks · '+(doc.citadel||'no Citadel reference')+' · REV '+doc.revision+' · UNVERIFIED';$('#rio-context-state').textContent=state.rioContext;rioMsg('RIO','Document summary attached locally: '+state.rioContext)}
function preparePrint(){
  sync();$$('.print-value').forEach(node=>node.remove());
  $$('#title,.heading-input,.text-input').forEach(input=>{
    const copy=document.createElement('div');copy.className='print-value '+(input.id==='title'?'print-title':input.classList.contains('heading-input')?'print-heading':'print-text');
    if(input.classList.contains('text-input'))input.value.split('\n').forEach((value,index)=>{if(index)copy.append(document.createTextNode('\n'));const line=document.createElement('p');line.className='print-line';line.textContent=value;copy.append(line)});else copy.textContent=input.value;
    input.after(copy);
  });
}
async function action(name){
  if(name==='save')await saveDoc();if(name==='export')await exportDoc();if(name==='print'){preparePrint();window.print()}if(name==='import')$('#import-file').click();
  if(name==='new'&&discardAllowed()){state.template='blank';state.current=newDoc();state.dirty=false;clearContext();renderDoc();go('build')}
  if(name==='delete-id'&&confirm('Delete the local PALACO ID? Existing document creator references remain.')){checkStorage();busy(true);try{if(await persist(null)){state.identity=null;renderIdentity();renderDoc();notice('Local ID deleted. Document source references were retained.')}}finally{busy(false)}}
  if(name==='rio-context')attachContext();if(name==='rio-clear')clearContext();
}
async function click(event){
  let node=event.target.closest('[data-goto]');if(node){go(node.dataset.goto);return}node=event.target.closest('[data-view]');if(node){go(node.dataset.view);return}
  if(state.busy&&event.target.closest('[data-template],[data-add],[data-action],[data-image-edit],[data-block],[data-restore],[data-open],[data-delete]')){event.preventDefault();notice('Please wait for the current operation to finish.');return}
  node=event.target.closest('[data-template]');if(node){if(!discardAllowed())return;state.template=node.dataset.template;state.current=newDoc();state.dirty=state.current.blocks.length>0;clearContext();renderDoc();return}
  node=event.target.closest('[data-add]');if(node){addBlock(node.dataset.add);return}
  node=event.target.closest('[data-action]');if(node){if(node.dataset.action==='insert-image'){event.preventDefault();await insertImage()}else await action(node.dataset.action);return}
  node=event.target.closest('[data-image-edit]');if(node){openImage(state.current.blocks.find(block=>block.id===node.dataset.imageEdit));return}
  node=event.target.closest('[data-block]');if(node){move(node.dataset.id,node.dataset.block);return}node=event.target.closest('[data-restore]');if(node){restoreRevision(node.dataset.restore);return}
  node=event.target.closest('[data-open]');if(node){if(!discardAllowed())return;state.current=M.clone(state.docs.find(doc=>doc.id===node.dataset.open));state.dirty=false;clearContext();go('build');return}
  node=event.target.closest('[data-delete]');if(node){if(!confirm('Delete this document and all its local revisions?'))return;checkStorage();const docs=state.docs.filter(doc=>doc.id!==node.dataset.delete),revisions={...state.revisions};delete revisions[node.dataset.delete];
    busy(true);try{if(await persist(state.identity,docs,revisions)){state.docs=docs;state.revisions=revisions;if(state.current.id===node.dataset.delete){state.current=newDoc();state.dirty=false;clearContext();renderDoc()}renderLibrary()}}finally{busy(false)}return}
  node=event.target.closest('[data-rio]');if(node){rioMsg('YOU',node.dataset.rio);rioMsg('RIO',rio(node.dataset.rio))}
}
document.addEventListener('click',event=>{click(event).catch(showError)});
document.addEventListener('input',event=>{const node=event.target.closest('[data-edit]');if(node){const block=state.current.blocks.find(item=>item.id===node.dataset.edit);if(block){block.text=node.value;fitText(node);markDirty()}}});
$('#identity-form').addEventListener('submit',event=>{event.preventDefault();saveIdentity(event.currentTarget).catch(showError)});
$('#image-file').addEventListener('change',()=>$('#image-file').setCustomValidity(''));
$('#import-file').addEventListener('change',event=>{importDoc(event.target.files[0]).catch(showError)});
$('#rio-form').addEventListener('submit',event=>{event.preventDefault();const input=$('#rio-input'),q=input.value.trim();if(q){rioMsg('YOU',q);rioMsg('RIO',rio(q));input.value=''}});
['title','purpose','citadel'].forEach(key=>$('#'+key).addEventListener('input',()=>{sync();markDirty();if(key==='title')fitText($('#title'))}));$('#visibility').addEventListener('change',()=>{sync();markDirty()});
window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue=''}});
window.addEventListener('beforeprint',preparePrint);
window.addEventListener('resize',fitDocument);
window.addEventListener('storage',event=>{if(event.key===KEY||event.key===null){state.storageBlocked=true;notice('PALACO data changed in another tab. Export your unsaved work, then reload before saving.',true)}});load();
})();
