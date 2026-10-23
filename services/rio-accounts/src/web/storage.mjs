import {DocumentVault} from '/api/storage/vault.mjs';
import {decodeDocument,MAX_BYTES} from '/api/storage/document-exchange.mjs';
const $=id=>document.getElementById(id);
const el=Object.fromEntries(['vault-account','vault-feedback','vault-connect','vault-logout','vault-form','vault-file',
  'vault-retention','vault-save','vault-staged','vault-staged-title','vault-staged-content','vault-usage','vault-refresh',
  'vault-list','vault-preview','document-title','document-source','document-content'].map(id=>[id,$(id)]));
let staged,sequence=0,fileRead=0,lastCatalog,lastDocument,poll;
const date=value=>new Date(value).toLocaleString('nl-NL');
const clearStaged=()=>{
  staged=undefined;fileRead++;el['vault-file'].value='';el['vault-save'].disabled=true;el['vault-staged'].hidden=true;
  el['vault-staged-title'].textContent='';el['vault-staged-content'].textContent='';
};
const labels={LIVE:'Bewaard',DELETED:'Gewist',EXPIRED:'Verlopen'};
function render(state){
  const ready=state.phase==='ready',locked=!ready||state.busy;
  el['vault-account'].textContent=ready?state.accountId:'';
  el['vault-logout'].disabled=!ready;
  el['vault-connect'].disabled=state.phase==='checking'||state.busy;
  for(const id of ['vault-file','vault-retention','vault-refresh'])el[id].disabled=locked;
  el['vault-save'].disabled=locked||!staged;
  if(!ready){
    sequence++;clearStaged();lastCatalog=undefined;lastDocument=undefined;el['vault-list'].replaceChildren();
    el['vault-usage'].textContent='';el['vault-preview'].hidden=true;
    for(const id of ['document-title','document-source','document-content'])el[id].textContent='';
    el['vault-feedback'].textContent=state.phase==='unavailable'
      ?'De opslag kon niet veilig worden gecontroleerd. Een bewaaractie kan al zijn uitgevoerd. Controleer opnieuw; herhaal een onbevestigde actie met hetzelfde bestand en dezelfde bewaartermijn.'
      :state.phase==='anonymous'?'Geen geldige testsessie. Meld je aan via de accountpagina.'
      :state.phase==='checking'?'Je testsessie en opslag worden gecontroleerd.'
      :'Lokale inhoud is gewist. Een lopende serveractie kan al zijn uitgevoerd.';
  }
  if(ready&&state.catalog!==lastCatalog){
    lastCatalog=state.catalog;
    const usage=state.catalog.usage,limits=state.catalog.limits;
    el['vault-usage'].textContent=`${usage.liveBytes} van ${limits.liveBytes} bytes in gebruik · ${usage.retainedObjects} van ${limits.lifetimeObjects} objectnummers gebruikt`;
    const rows=state.catalog.objects.map(row=>{
      const li=document.createElement('li');li.dataset.objectId=row.objectId;li.dataset.state=row.state;
      const description=document.createElement('p');description.className='preview-note';
      description.textContent=`${row.objectId} · ${labels[row.state]} · ${row.liveBytes} bytes · ${row.state==='LIVE'?'Verloopt: '+date(row.expiresAt):'Beëindigd: '+date(row.endedAt)}`;
      li.append(description);
      const actions=document.createElement('div');actions.className='object-actions';
      if(row.state==='LIVE')for(const [action,label] of [['open','Document openen'],['erase','Document wissen']]){
        const button=document.createElement('button');button.type='button';button.className='button button-outline';
        button.textContent=label;button.dataset.action=action;button.disabled=locked;
        button.addEventListener('click',()=>void perform(()=>action==='open'?vault.open(row.objectId):vault.erase(row.objectId),
          action==='open'?'Document gecontroleerd en geopend.':'Wissen bevestigd; bekijk de actuele status in de lijst.'));
        actions.append(button);
      }
      if(actions.childElementCount)li.append(actions);
      return li;
    });
    el['vault-list'].replaceChildren(...rows);
  }
  for(const button of el['vault-list'].querySelectorAll('button'))button.disabled=locked;
  if(state.document!==lastDocument){
    lastDocument=state.document;const packet=state.document;
    el['vault-preview'].hidden=!packet;
    el['document-title'].textContent=packet?.document.title||'';
    el['document-content'].textContent=packet?.document.content||'';
    el['document-source'].textContent=packet?`${packet.origin} · ${packet.document.status} · gebruikersopgave`:'';
  }
}
const vault=new DocumentVault(globalThis.fetch.bind(globalThis),render);
async function perform(action,message){
  const stamp=sequence;
  try{await action();if(stamp===sequence&&vault.snapshot().phase==='ready')el['vault-feedback'].textContent=message;}
  catch(error){if(stamp===sequence)el['vault-feedback'].textContent=error?.code==='PENDING_SAVE'
    ?'Bevestig eerst de onbevestigde bewaaractie met hetzelfde bestand en dezelfde bewaartermijn.'
    :'De actie is niet bevestigd. Controleer je testsessie en de actuele opslag opnieuw.';}
}
async function connect(){
  try{await vault.connect();if(vault.snapshot().phase==='ready')el['vault-feedback'].textContent=vault.snapshot().pendingSave
    ?'Je opslag is gecontroleerd. Bevestig de onbevestigde bewaaractie met hetzelfde bestand en dezelfde bewaartermijn.'
    :'Je eigen proefopslag is gecontroleerd.';}catch{}
}
el['vault-connect'].addEventListener('click',()=>void connect());
el['vault-refresh'].addEventListener('click',()=>void perform(()=>vault.refresh(),'Je opslag is opnieuw gecontroleerd.'));
el['vault-logout'].addEventListener('click',()=>{void vault.logout().catch(()=>{});});
el['vault-file'].addEventListener('change',()=>{
  const file=el['vault-file'].files?.[0];clearStaged();const stamp=sequence,read=++fileRead;
  if(!file||file.size<1||file.size>MAX_BYTES){el['vault-feedback'].textContent='Kies een geldig documentbestand van maximaal 16 KiB.';return;}
  void(async()=>{
    try{const bytes=new Uint8Array(await file.arrayBuffer()),packet=await decodeDocument(bytes);
      if(stamp!==sequence||read!==fileRead||vault.snapshot().phase!=='ready')return;
      staged=bytes;el['vault-staged-title'].textContent=packet.document.title;
      el['vault-staged-content'].textContent=packet.document.content;el['vault-staged'].hidden=false;
      el['vault-feedback'].textContent='Bestand gecontroleerd. Kies je bewaartermijn en bevestig bewaren.';render(vault.snapshot());
    }catch{if(stamp===sequence&&read===fileRead)el['vault-feedback'].textContent='Dit bestand heeft geen geldig documentformaat of geldige inhoudshash.';}
  })();
});
el['vault-form'].addEventListener('submit',event=>{
  event.preventDefault();if(!staged)return;const bytes=Uint8Array.from(staged),stamp=sequence;
  void perform(async()=>{await vault.save(bytes,Number(el['vault-retention'].value));if(stamp===sequence)clearStaged();},'Bewaren bevestigd; bekijk de actuele status in de lijst.');
});
function stop(){clearInterval(poll);vault.close();}
function start(){clearInterval(poll);void connect();poll=setInterval(()=>{if(!document.hidden)void vault.check().catch(()=>{});},5000);}
window.addEventListener('pagehide',stop);
window.addEventListener('pageshow',()=>{if(!document.hidden)start();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else start();});
render(vault.snapshot());
