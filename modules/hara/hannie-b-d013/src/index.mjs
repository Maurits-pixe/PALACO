import {realpathSync} from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { validate, canonical } from './value.mjs';
const anchorWall=Date.now(), anchorMono=performance.now();
let highestTime=anchorWall;
const trustedNow=()=>highestTime=Math.max(highestTime,Date.now(),Math.ceil(anchorWall+performance.now()-anchorMono));
const witnesses=new Set();
const key=(path,context,request)=>canonical({path,context,request});
const worker=fileURLToPath(new URL('./worker.mjs',import.meta.url));
const databasePathForLock=input=>input.databasePath;
async function launch(input, env={}) {
  return new Promise(resolve => {
    const child=spawn('/usr/bin/flock',['--exclusive','--no-fork',databasePathForLock(input)+'.release.lock',process.execPath,'--disable-warning=ExperimentalWarning',worker],{env:{...process.env,...env},stdio:['ignore','ignore','pipe','ipc']});
    let message,stderr=''; const timer=setTimeout(()=>child.kill('SIGKILL'),15000);
    child.stderr.on('data',x=>stderr+=x); child.on('message',x=>{message=x;});
    child.on('error',e=>{message={status:'RESULT_UNKNOWN',code:e.message};});
    child.on('exit',(code,signal)=>{clearTimeout(timer);resolve({pid:child.pid,code,signal,message,stderr});});
    child.send({...input,timeFloor:trustedNow(),timeAnchorMono:process.hrtime.bigint().toString(),deadlineProof:input.request ? witnesses.has(key(input.databasePath,input.context,input.request)) : false});
  });
}
export async function recover(databasePath,context,request) {
  databasePath=realpathSync(databasePath);
  validate(context,request); const run=await launch({mode:'read',databasePath,context,request});
  if(run.code!==0 || run.stderr || !run.message) return {status:'RESULT_UNKNOWN',code:'RECONSTRUCTION_PROCESS_FAILED',trace:run};
  return {...run.message,readProcess:{pid:run.pid,exit:run.code}};
}
export async function execute(databasePath,context,request, trustedHarnessEnvironment={}) {
  databasePath=realpathSync(databasePath);
  validate(context,request); const bound=JSON.parse(canonical({context,request}));
  const writer=await launch({mode:'write',databasePath,...bound},trustedHarnessEnvironment);
  if (writer.message?.created===true) witnesses.add(key(databasePath,bound.context,bound.request));
  // Ignore every positive writer message, including a deliberately false precommit ACK.
  const reconstructed=await recover(databasePath,bound.context,bound.request);
  if(writer.message?.status==='DENIED' && reconstructed.code==='NO_DURABLE_COMMIT') return {...writer.message,writer};
  return {...reconstructed,writer};
}
export async function revoke(databasePath,context,grantId) {
  databasePath=realpathSync(databasePath);
  const writer=await launch({mode:'revoke',databasePath,context,grantId});
  // Revocation is only reported from fresh readback by the caller/fixture; a lost ACK is not success.
  return {status:'RECONSTRUCTION_REQUIRED',writer};
}
