import assert from 'node:assert/strict';
import test from 'node:test';
import {
  POST_CONSENT_TYPE, safePostConsentObservation,
  postConsentOwnAccountRead,
} from './post-consent-observation.mjs';

const CANARY='PRIVATE_POST_CONSENT_SECRET_CANARY';
const allowed={
  stage:'after-grant',grantRevision:4,storedRevision:4,
  accountStatus:401,accountRequestFailed:false,
  sessionCookiePresent:true,errorKind:'other',
};
const annotate=(item,type=POST_CONSENT_TYPE)=>[{
  type,description:typeof item==='string'?item:JSON.stringify(item),
}];
const reject=item=>{
  const filtered=safePostConsentObservation(annotate(item));
  assert.equal(filtered,undefined);
  assert.equal(JSON.stringify({filtered}).includes(CANARY),false);
};
const fakePage=(jar=[{name:'__Host-rio_session',value:CANARY}])=>({
  context:()=>({cookies:async origin=>{
    assert.equal(origin,'https://localhost:8088');return jar;
  }}),
});
const revision={grantRevision:4,storedRevision:4};

test('accepts strict failure-only synthetic status and copies nothing private',()=>{
  assert.deepEqual(safePostConsentObservation(annotate(allowed)),allowed);
  const other={...allowed,accountStatus:null,accountRequestFailed:true,
    errorKind:'network-changed',sessionCookiePresent:null};
  assert.deepEqual(safePostConsentObservation(annotate(other)),other);
  for(const status of [100,302,401,403,429,503,599]){
    assert.equal(safePostConsentObservation(annotate({...allowed,accountStatus:status}))?.accountStatus,status);
  }
  assert.deepEqual(safePostConsentObservation(annotate({...allowed,sessionCookiePresent:false})),
    {...allowed,sessionCookiePresent:false});
});

test('rejects secrets, extra keys, wrong scopes, invalid revisions and statuses',()=>{
  for(const key of Object.keys(allowed)){const missing={...allowed};delete missing[key];reject(missing);}
  for(const extra of [
    {cookieValue:CANARY}, {accountId:CANARY},{username:CANARY},
    {callbackUrl:'https://localhost:8088/auth/callback?code='+CANARY},
    {csrfToken:CANARY}, {rawError:CANARY}, {consentReceipt:{revision:4,token:CANARY}},
  ])reject({...allowed,...extra});
  for(const bad of [
    {stage:'before-grant'}, {stage:CANARY}, {grantRevision:-1},
    {storedRevision:1.5},{grantRevision:1000000001},{storedRevision:CANARY},
    {accountStatus:200},{accountStatus:99},{accountStatus:600},
    {accountStatus:'401'}, {accountStatus:CANARY}, {accountStatus:null},
    {accountRequestFailed:true,accountStatus:401},
    {accountRequestFailed:'false'}, {sessionCookiePresent:CANARY},
    {sessionCookiePresent:1},{errorKind:CANARY},
  ])reject({...allowed,...bad});
  assert.equal(safePostConsentObservation([]),undefined);
  assert.equal(safePostConsentObservation([...annotate(allowed),...annotate(allowed)]),undefined);
  assert.equal(safePostConsentObservation(annotate('{')),undefined);
  assert.equal(safePostConsentObservation(annotate(allowed,'other')),undefined);
  assert.equal(safePostConsentObservation(annotate(CANARY.repeat(200))),undefined);
});

test('successful post-consent account GET issues exactly one read, no annotation',async()=>{
  let calls=0;const info={annotations:[]};
  const result=await postConsentOwnAccountRead(fakePage(),info,revision,async()=>{
    calls++;return {status:200,data:{accountId:'synthetic-test-only'}};
  });
  assert.equal(calls,1);assert.equal(result.status,200);
  assert.deepEqual(info.annotations,[]);
});

test('post-consent HTTP 401 is observed, not retried or changed into success',async()=>{
  let calls=0;const info={annotations:[]};
  const result=await postConsentOwnAccountRead(fakePage(),info,revision,async()=>{
    calls++;return {status:401,data:null};
  });
  assert.equal(calls,1);assert.equal(result.status,401);
  assert.equal(info.annotations.length,1);
  assert.deepEqual(safePostConsentObservation(info.annotations),allowed);
  assert.equal(JSON.stringify(info.annotations).includes(CANARY),false);
});

test('transport failure propagates without retry, only bounded kind and nullable cookie',async()=>{
  let calls=0;const info={annotations:[]};
  const page={context:()=>({cookies:async()=>{throw new Error(CANARY);}})};
  const original=new Error('net::ERR_NETWORK_CHANGED '+CANARY);
  await assert.rejects(postConsentOwnAccountRead(page,info,revision,async()=>{
    calls++;throw original;
  }),error=>error===original);
  assert.equal(calls,1);
  assert.deepEqual(safePostConsentObservation(info.annotations),{
    ...allowed,accountStatus:null,accountRequestFailed:true,
    sessionCookiePresent:null,errorKind:'network-changed',
  });
  assert.equal(JSON.stringify(info.annotations).includes(CANARY),false);
});
