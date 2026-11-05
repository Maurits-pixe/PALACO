// Test-fixture provisioning only: no credential verification or public admission API.
import {realpathSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {basename,dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {canonical} from '../src/value.mjs';
const worker=fileURLToPath(new URL('./approval-store-worker.mjs',import.meta.url));
export async function fixtureCall(mode,path,context,request,extra={},environment={}) {
 path=realpathSync(path);
 if(dirname(dirname(path))!==realpathSync(tmpdir())||!basename(dirname(path)).startsWith('hara-vd-')||basename(path)!=='calendar.sqlite'||context.owner!=='synthetic-owner'||context.tenant!=='synthetic-tenant'||context.session!=='synthetic-session')throw Error('SYNTHETIC_FIXTURE_ONLY');
 const input=JSON.parse(canonical({mode,path,context,request,...extra}));
 return await new Promise((resolve,reject)=>{
  const p=spawn('/usr/bin/flock',['--exclusive','--no-fork',path+'.release.lock',process.execPath,'--disable-warning=ExperimentalWarning',worker],{env:{...process.env,...environment},stdio:['ignore','ignore','pipe','ipc']});let message,stderr='';
  const timer=setTimeout(()=>p.kill('SIGKILL'),10000);p.stderr.on('data',x=>stderr+=x);p.on('message',x=>{message=x;});p.on('error',reject);p.on('close',(code,signal)=>{clearTimeout(timer);resolve({code,signal,message,stderr});});p.send(input);
 });
}
export async function prepareChallenge(f,expiry=f.expiry){return fixtureCall('prepare',f.path,f.context,f.request,{challengeExpiry:expiry,approvalExpiry:f.approvalExpiry});}
export async function inspectApproval(f,challengeId){return fixtureCall('read',f.path,f.context,f.request,{challengeId});}
export async function confirmChallenge(f,challengeId,selection,choices,{phase='normal',environment={}}={}){
 const writer=await fixtureCall('confirm',f.path,f.context,f.request,{challengeId,selection,choices,phase},environment);
 const read=await inspectApproval(f,challengeId);return {writer,read};
}
