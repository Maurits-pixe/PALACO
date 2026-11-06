import {realpathSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {validate,canonical} from './value.mjs';
const wall=Date.now(),mono=performance.now();let highest=wall;
const now=()=>highest=Math.max(highest,Date.now(),Math.ceil(wall+performance.now()-mono));
const witnesses=new Map();
const key=(path,context,request)=>canonical({path,context,request});
const worker=fileURLToPath(new URL('./worker.mjs',import.meta.url));
async function launch(input,environment={}) {
  return new Promise(resolve=>{
    const child=spawn('/usr/bin/flock',['--exclusive','--no-fork',input.databasePath+'.release.lock',process.execPath,'--disable-warning=ExperimentalWarning',worker],{env:{...process.env,...environment},stdio:['ignore','ignore','pipe','ipc']});
    let message,stderr='';const timer=setTimeout(()=>child.kill('SIGKILL'),15000);
    child.stderr.on('data',x=>stderr+=x);
    child.on('message',x=>{message=x;});
    child.on('error',e=>{message={status:'RESULT_UNKNOWN',code:e.code};});
    child.on('close',(code,signal)=>{clearTimeout(timer);resolve({pid:child.pid,code,signal,message,stderr});});
    child.send({...input,timeFloor:now(),timeAnchorMono:process.hrtime.bigint().toString(),expectedValidationAt:input.request?witnesses.get(key(input.databasePath,input.context,input.request))??null:null},error=>{if(error)message={status:'RESULT_UNKNOWN',code:'IPC_FAILED'};});
  });
}
export async function recover(path,context,request,readCapability=null) {
  path=realpathSync(path);validate(context,request);
  const bound=JSON.parse(canonical({context,request,readCapability}));
  const run=await launch({mode:'read',databasePath:path,...bound});
  if(run.code!==0||run.stderr||!run.message)return {status:'RESULT_UNKNOWN',code:'READ_PROCESS_FAILED',trace:run};
  return {...run.message,readProcess:{pid:run.pid,exit:run.code}};
}
export async function execute(path,context,request,{readCapability=null,trustedHarnessEnvironment={}}={}) {
  path=realpathSync(path);validate(context,request);
  const bound=JSON.parse(canonical({context,request}));
  const writer=await launch({mode:'write',databasePath:path,...bound},trustedHarnessEnvironment);
  if(writer.message?.created===true&&Number.isSafeInteger(writer.message.validatedAt))
    witnesses.set(key(path,bound.context,bound.request),writer.message.validatedAt);
  const reconstructed=await recover(path,bound.context,bound.request,readCapability);
  if(writer.message?.status==='DENIED'&&reconstructed.code==='NO_DURABLE_COMMIT')return {...writer.message,writer};
  return {...reconstructed,writer};
}
export async function revoke(path,context,grantId,{readGrant=false}={}) {
  path=realpathSync(path);
  const writer=await launch({mode:readGrant?'revokeRead':'revoke',databasePath:path,context:JSON.parse(canonical(context)),grantId});
  return {status:'RECONSTRUCTION_REQUIRED',writer};
}
