import assert from 'node:assert/strict';
import test from 'node:test';
import { POST_CONSENT_TYPE } from './post-consent-observation.mjs';
import { classifyPostConsentFailure } from './post-consent-triage.mjs';

const CANARY='DO_NOT_EXPORT_SESSION_OR_CODE_CANARY';
const base={stage:'after-grant',grantRevision:2,storedRevision:2,
  accountStatus:401,accountRequestFailed:false,
  sessionCookiePresent:true,errorKind:'other'};
const evidence=data=>[{type:POST_CONSENT_TYPE,description:JSON.stringify(data)}];

test('classification is a limited symptom, never a diagnosis or release',()=>{
  const cases=[
    [{accountStatus:401},'ACCESS_DENIED'],
    [{accountStatus:403},'ACCESS_DENIED'],
    [{accountStatus:500},'SERVER_RESPONSE_ERROR'],
    [{accountStatus:503},'SERVER_RESPONSE_ERROR'],
    [{accountStatus:302},'UNEXPECTED_REDIRECT'],
    [{accountStatus:429},'HTTP_UNEXPECTED'],
    [{accountStatus:null,accountRequestFailed:true,errorKind:'network-changed'},'TRANSPORT_FAILURE'],
    [{accountStatus:null,accountRequestFailed:true,errorKind:'connection-reset',sessionCookiePresent:null},'TRANSPORT_FAILURE'],
  ];
  for(const [difference,expected] of cases){
    const actual=classifyPostConsentFailure(evidence({...base,...difference}));
    assert.equal(actual.accepted,true);
    assert.equal(actual.symptom,expected);
    assert.equal(actual.rootCause,'UNKNOWN');
    assert.equal(actual.decision,'HOLD');
    assert.equal(actual.observed.accountStatus,Object.hasOwn(difference,'accountStatus')?difference.accountStatus:base.accountStatus);
    assert.equal(Object.hasOwn(actual,'authorized'),false);
    assert.equal(Object.hasOwn(actual,'accountActive'),false);
  }
});

test('cookie boolean and revision are observations, never authorization or causal conclusions',()=>{
  for(const sessionCookiePresent of [true,false,null]){
    for(const revision of [0,1,1000000000]){
      const actual=classifyPostConsentFailure(evidence({
        ...base,grantRevision:revision,storedRevision:revision,sessionCookiePresent,
      }));
      assert.equal(actual.accepted,true);
      assert.equal(actual.observed.sessionCookiePresent,sessionCookiePresent);
      assert.equal(actual.rootCause,'UNKNOWN');
      assert.equal(actual.decision,'HOLD');
    }
  }
});

test('poisoned, fabricated, duplicated or absent evidence is unusable and HOLD',()=>{
  const invalid=[
    [],evidence({...base,accountStatus:200}),
    evidence({...base,accountId:CANARY}),
    evidence({...base,cookie:CANARY}),
    evidence({...base,callbackUrl:'https://localhost:8088/auth/callback?code='+CANARY}),
    evidence({...base,accountStatus:'401'}),
    evidence({...base,errorKind:CANARY}),
    [...evidence(base),...evidence(base)],
  ];
  for(const item of invalid){
    const result=classifyPostConsentFailure(item);
    assert.deepEqual(result,{
      accepted:false,symptom:'EVIDENCE_UNUSABLE',
      next:'RETAIN_RAW_PRIVATE_EVIDENCE_LOCALLY',rootCause:'UNKNOWN',decision:'HOLD',
    });
    assert.equal(JSON.stringify(result).includes(CANARY),false);
  }
});
