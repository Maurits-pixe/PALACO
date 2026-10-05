import { fork } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { validate, canonical } from './value.mjs';
const worker=fileURLToPath(new URL('./worker.mjs',import.meta.url));
async function launch(input, env={}) {
  return new Promise(resolve => {
    const child=fork(worker,[],{execArgv:['--disable-warning=ExperimentalWarning'],env:{...process.env,...env},stdio:['ignore','ignore','pipe','ipc']});
    let message,stderr=''; const timer=setTimeout(()=>child.kill('SIGKILL'),15000);
    child.stderr.on('data',x=>stderr+=x); child.on('message',x=>{message=x;});
    child.on('error',e=>{message={status:'RESULT_UNKNOWN',code:e.message};});
    child.on('exit',(code,signal)=>{clearTimeout(timer);resolve({pid:child.pid,code,signal,message,stderr});});
    child.send(input);
  });
}
export async function recover(databasePath,context,request) {
  validate(context,request); const run=await launch({mode:'read',databasePath,context,request});
  if(run.code!==0 || run.stderr || !run.message) return {status:'RESULT_UNKNOWN',code:'RECONSTRUCTION_PROCESS_FAILED',trace:run};
  return {...run.message,readProcess:{pid:run.pid,exit:run.code}};
}
export async function execute(databasePath,context,request, trustedHarnessEnvironment={}) {
  validate(context,request); const bound=JSON.parse(canonical({context,request}));
  const writer=await launch({mode:'write',databasePath,...bound},trustedHarnessEnvironment);
  // Ignore every positive writer message, including a deliberately false precommit ACK.
  const reconstructed=await recover(databasePath,bound.context,bound.request);
  if(writer.message?.status==='DENIED' && reconstructed.code==='NO_DURABLE_COMMIT') return {...writer.message,writer};
  return {...reconstructed,writer};
}
export async function revoke(databasePath,context,grantId) {
  const writer=await launch({mode:'revoke',databasePath,context,grantId});
  // Revocation is only reported from fresh readback by the caller/fixture; a lost ACK is not success.
  return {status:'RECONSTRUCTION_REQUIRED',writer};
}
