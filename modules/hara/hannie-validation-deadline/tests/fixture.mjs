import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {PROFILE,canonical,digest} from '../src/value.mjs';
export function fixture(t,{lifetime=30000,approvalLifetime=lifetime,readLifetime=30000,provisionApproval=true}={}) {
 const dir=mkdtempSync(join(tmpdir(),'hara-vd-')),path=join(dir,'calendar.sqlite');t.after(()=>rmSync(dir,{recursive:true,force:true}));
 const context={owner:'synthetic-owner',tenant:'synthetic-tenant',session:'synthetic-session'};
 const request={contractProfile:PROFILE,finishAfterExpiry:true,operationId:'operation-1',calendarId:'calendar-1',eventId:'event-1',grantId:'grant-1',generation:1,approvalId:'approval-1',title:'Synthetic private event'};
 const readCapability={grantId:'read-1',generation:1};
 const db=new DatabaseSync(path);db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;');db.exec(readFileSync(new URL('../src/schema.sql',import.meta.url),'utf8'));
 const start=Date.now(),expiry=start+lifetime,approvalExpiry=start+approvalLifetime,readExpiry=start+readLifetime;
 db.prepare('INSERT INTO calendars VALUES (?,?,?,1)').run(request.calendarId,context.owner,context.tenant);
 db.prepare('INSERT INTO grants VALUES (?,?,?,?,?,1,?,\'ACTIVE\',\'CREATE_OWN_EVENT\',?,1)').run(request.grantId,request.calendarId,context.owner,context.tenant,context.session,expiry,PROFILE);
 if(provisionApproval) db.prepare('INSERT INTO approvals VALUES (?,?,?,?,?,0,?,1)').run(request.approvalId,request.grantId,digest(request),digest(context),approvalExpiry,PROFILE);
 db.prepare("INSERT INTO read_grants VALUES (?,?,?,?,?,1,?,'ACTIVE','READ_OWN_EVENT')").run(readCapability.grantId,request.calendarId,context.owner,context.tenant,context.session,readExpiry);db.close();
 return {dir,path,context,request,readCapability,expiry,approvalExpiry,readExpiry};
}
export function inspect(path,fn){const db=new DatabaseSync(path,{readOnly:true});try{return fn(db);}finally{db.close();}}
export function mutate(path,fn){const db=new DatabaseSync(path);try{return fn(db);}finally{db.close();}}
export const state=path=>inspect(path,db=>canonical(Object.fromEntries(['audit','decisions','events','versions','receipts','approvals','grants','read_grants',...(db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fixture_challenges'").get()?['fixture_challenges']:[])].map(k=>[k,JSON.parse(JSON.stringify(db.prepare('SELECT * FROM '+k+' ORDER BY 1').all()))]))));
export const counts=path=>inspect(path,db=>Object.fromEntries(['audit','decisions','events','versions','receipts'].map(k=>[k,db.prepare('SELECT COUNT(*) n FROM '+k).get().n])));
