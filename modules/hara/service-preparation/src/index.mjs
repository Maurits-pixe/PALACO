// Local proposal preparation only. No host authentication, I/O or dispatch.
import {createHash} from 'node:crypto';
import {prepareConsent} from '../../hannie-validation-deadline/src/client.mjs';

const requireThat=(ok)=>{if(!ok)throw Error('INVALID_SERVICE_TASK');};
// A bounded JSON snapshot rejects accessors, cycles and exotic objects before
// reading field values. Inputs are ordinary data, never executable callbacks.
function snapshot(value,depth=0,seen=new Set()) {
 requireThat(depth<=12);
 if(value===null||typeof value==='boolean')return value;
 if(typeof value==='string'){requireThat(value.length<=4096);return value;}
 if(typeof value==='number'){requireThat(Number.isSafeInteger(value));return value;}
 requireThat(value&&typeof value==='object'&&!seen.has(value));
 const array=Array.isArray(value);
 requireThat(Object.getPrototypeOf(value)===(array?Array.prototype:Object.prototype));
 const descriptors=Object.getOwnPropertyDescriptors(value),keys=Reflect.ownKeys(descriptors);
 requireThat(keys.length<=100&&keys.every(k=>typeof k==='string'));
 for(const k of keys)requireThat('value' in descriptors[k]&&(array&&k==='length'||descriptors[k].enumerable));
 seen.add(value);
 let result;
 if(array){
  requireThat(value.length<=32&&keys.length===value.length+1);
  result=Array.from({length:value.length},(_,i)=>{requireThat(Object.hasOwn(descriptors,String(i)));return snapshot(descriptors[i].value,depth+1,seen);});
 }else{
  result=Object.fromEntries(keys.sort().map(k=>[k,snapshot(descriptors[k].value,depth+1,seen)]));
 }
 seen.delete(value);return result;
}
function exact(value,keys){requireThat(value&&!Array.isArray(value)&&typeof value==='object'&&Object.keys(value).sort().join(',')===[...keys].sort().join(','));}
function text(value,max=1000){requireThat(typeof value==='string'&&value.trim().length>0&&value.length<=max&&!/[\u0000-\u001f\u007f]/u.test(value));}
function freeze(value){if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;}

export function prepareServiceTask(input) {
 const task=snapshot(input);let proposal;
 if(task?.purpose==='CONSUMER'){
  exact(task,['purpose','context','request','deadlines']);
  // Reuse the candidate's exact context/request/profile and disclosure contract.
  proposal={action:'CREATE_OWN_EVENT',preview:prepareConsent(task.context,task.request,task.deadlines)};
 }else if(task?.purpose==='MAINTENANCE'){
  exact(task,['purpose','repository','sourceCommit','changeSummary','verificationPlan']);
  text(task.repository,160);requireThat(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(task.repository));
  requireThat(typeof task.sourceCommit==='string'&&/^[a-f0-9]{40}$/.test(task.sourceCommit));
  text(task.changeSummary);
  requireThat(Array.isArray(task.verificationPlan)&&task.verificationPlan.length>0&&task.verificationPlan.length<=12);
  task.verificationPlan.forEach(step=>text(step));
  proposal={action:'PREPARE_MAINTENANCE_CHANGE',repository:task.repository,sourceCommit:task.sourceCommit,changeSummary:task.changeSummary,verificationPlan:task.verificationPlan};
 }else throw Error('UNSUPPORTED_SERVICE_PURPOSE');
 const binding={contract:'HARA_SERVICE_PROPOSAL_V1',requestedRoute:'PALACO ONE',purpose:task.purpose,proposal};
 // snapshot sorts every object, including the reused preview, for stable bytes.
 const proposalDigest=createHash('sha256').update(JSON.stringify(snapshot(binding))).digest('hex');
 return freeze({...binding,proposalDigest,status:'DRAFT_REQUIRES_HOST_VERIFICATION',authorityGranted:false,hostBinding:'UNRESOLVED',canExecute:false,
  explanation:task.purpose==='CONSUMER'?'Agenda-opdracht voorbereid. Er is nog niets uitgevoerd; eigenaar, toestemming en tijd moeten door de host worden gecontroleerd.':'Onderhoudsvoorstel voorbereid. De bronversie is opgegeven, niet geverifieerd. Uitvoering vereist afzonderlijke onderhoudsbevoegdheid.'});
}
