import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { classifyLoginEndpoint, classifyLoginError, observeMobileLogin, safeMobileLoginObservation } from './login-observation.mjs';

const TYPE = 'rio-mobile-login-observation';
const PRIVATE = 'PRIVATE_LOGIN_DIAGNOSTIC_CANARY';
const allowed = {
  actorCase: 'alpha', stage: 'waiting-for-account', pageKind: 'bff-home',
  accountVisible: false, loginButtonVisible: false,
  documentStatuses: [200], meStatuses: [401, 200], consentStatuses: [503],
  providerSubmitStatuses: [302], callbackStatuses: [200],
  providerSubmitRequests: 1, callbackRequests: 1,
  postCallbackMeRequests: 1, postCallbackMeStatuses: [200],
  sessionCookiePresentAtFailure: true,
  documentRequestFailed: false, meRequestFailed: false, consentRequestFailed: true,
  providerSubmitRequestFailed: false, callbackRequestFailed: true,
  postCallbackMeRequestFailed: false,
  errorKind: 'timeout', feedbackBucket: 'service_unavailable',
};
const annotate = (value, type = TYPE) => [{
  type, description: typeof value === 'string' ? value : JSON.stringify(value),
}];
const expectRejected = (value) => {
  const observation = safeMobileLoginObservation(annotate(value));
  assert.equal(observation, undefined);
  assert.equal(JSON.stringify({ observation }).includes(PRIVATE), false);
};

test('preserves only the exact typed mobile login observation in independent copies', () => {
  const first = safeMobileLoginObservation(annotate(allowed));
  assert.deepEqual(first, allowed);
  assert.notEqual(first, allowed);
  for (const key of ['documentStatuses', 'meStatuses', 'consentStatuses', 'providerSubmitStatuses', 'callbackStatuses', 'postCallbackMeStatuses']) {
    assert.notEqual(first[key], allowed[key]);
  }
  first.documentStatuses.push(599);
  first.meStatuses[0] = 599;
  first.consentStatuses.length = 0;
  first.actorCase = 'beta';
  assert.deepEqual(safeMobileLoginObservation(annotate(allowed)), allowed);
  const missingVisibility = {
    ...allowed, accountVisible: null, loginButtonVisible: null, pageKind: 'unavailable',
  };
  assert.deepEqual(safeMobileLoginObservation(annotate(missingVisibility)), missingVisibility);
});

test('missing, duplicate, malformed and wrongly typed annotations disclose no observation', () => {
  for (const annotations of [
    [], annotate(allowed, 'rio-other-observation'),
    [...annotate(allowed), ...annotate(allowed)],
    annotate('{'), annotate('null'), annotate('[]'),
    [{ type: TYPE, description: null }],
    [{ type: TYPE, description: 200 }],
    [{ type: TYPE }],
  ]) {
    assert.equal(safeMobileLoginObservation(annotations), undefined);
  }
});

test('rejects every missing field and any extra credential, URL, raw error or DOM data', () => {
  for (const key of Object.keys(allowed)) {
    const incomplete = { ...allowed };
    delete incomplete[key];
    expectRejected(incomplete);
  }
  for (const extra of [
    { url: 'https://localhost:8088/auth/callback?code=' + PRIVATE },
    { access_token: PRIVATE }, { password: PRIVATE }, { username: PRIVATE },
    { cookie: PRIVATE }, { csrfToken: PRIVATE }, { rawError: PRIVATE },
    { domText: PRIVATE }, { endpoint: '/api/me?token=' + PRIVATE },
    { accountActive: true }, { authorityGranted: true },
  ]) {
    expectRejected({ ...allowed, ...extra });
  }
});

test('accepts only the enumerated stage, actor, page, feedback and error kinds with fixed types', () => {
  for (const [key, values] of [
    ['actorCase', ['alpha', 'beta']],
    ['stage', [
      'initial', 'opening-bff', 'landing', 'starting-oidc', 'waiting-for-provider',
      'submitting-credentials', 'waiting-for-bff', 'waiting-for-account',
      'waiting-for-consent', 'ready',
    ]],
    ['pageKind', ['unavailable', 'bff-home', 'provider', 'other']],
    ['errorKind', [
      'aborted', 'connection-refused', 'connection-reset', 'connection-closed', 'empty-response',
      'http2-protocol', 'tls-certificate', 'network-changed', 'timeout',
      'target-closed', 'other',
    ]],
    ['feedbackBucket', [
      'unavailable', 'empty', 'confirmed', 'service_unavailable',
      'expired', 'changed', 'invalid_response', 'other',
    ]],
  ]) {
    for (const value of values) {
      const candidate = { ...allowed, [key]: value };
      assert.deepEqual(safeMobileLoginObservation(annotate(candidate)), candidate);
    }
    for (const value of [PRIVATE, '', null, 1, {}, []]) {
      expectRejected({ ...allowed, [key]: value });
    }
  }
  for (const key of ['accountVisible', 'loginButtonVisible']) {
    for (const value of [true, false, null]) {
      const candidate = { ...allowed, [key]: value };
      assert.deepEqual(safeMobileLoginObservation(annotate(candidate)), candidate);
    }
    for (const value of ['true', 0, PRIVATE, {}, []]) expectRejected({ ...allowed, [key]: value });
  }
  for (const key of ['documentRequestFailed', 'meRequestFailed', 'consentRequestFailed',
    'providerSubmitRequestFailed', 'callbackRequestFailed', 'postCallbackMeRequestFailed']) {
    for (const value of ['false', null, 0, PRIVATE, {}, []]) expectRejected({ ...allowed, [key]: value });
  }
});

test('endpoint observations admit only bounded integer HTTP statuses and never paths or bodies', () => {
  for (const key of ['documentStatuses', 'meStatuses', 'consentStatuses', 'providerSubmitStatuses', 'callbackStatuses', 'postCallbackMeStatuses']) {
    for (const value of [[], [100, 599], Array(8).fill(200)]) {
      const candidate = { ...allowed, [key]: value };
      assert.deepEqual(safeMobileLoginObservation(annotate(candidate)), candidate);
    }
    for (const value of [
      [99], [600], [200.5], ['200'], [null], [true], Array(9).fill(200),
      { '/api/me': 200 }, [{ status: 200, body: PRIVATE }],
      ['https://localhost:8088/?code=' + PRIVATE],
    ]) expectRejected({ ...allowed, [key]: value });
  }
});

test('annotation size limit includes padding and rejects oversized private text without echoing', () => {
  const serialized = JSON.stringify(allowed);
  assert.ok(serialized.length < 1024);
  const boundary = serialized + ' '.repeat(1024 - serialized.length);
  assert.deepEqual(safeMobileLoginObservation(annotate(boundary)), allowed);
  assert.equal(safeMobileLoginObservation(annotate(boundary + ' ')), undefined);
  expectRejected(JSON.stringify({ ...allowed, rawError: PRIVATE.repeat(100) }));
});

test('local browser errors become fixed diagnostic kinds without exposing appended secrets', () => {
  for (const [code, expected] of [
    ['ERR_ABORTED', 'aborted'],
    ['ERR_CONNECTION_REFUSED', 'connection-refused'],
    ['ERR_CONNECTION_RESET', 'connection-reset'],
    ['ERR_CONNECTION_CLOSED', 'connection-closed'],
    ['ERR_EMPTY_RESPONSE', 'empty-response'],
    ['ERR_HTTP2_PROTOCOL_ERROR', 'http2-protocol'],
    ['ERR_CERT_AUTHORITY_INVALID', 'tls-certificate'],
    ['ERR_NETWORK_CHANGED', 'network-changed'],
  ]) {
    const result = classifyLoginError({
      name: 'Error', message: 'page.goto: net::' + code + ' at https://localhost:8088/?code=' + PRIVATE,
    });
    assert.equal(result, expected);
    assert.equal(result.includes(PRIVATE), false);
  }
  assert.equal(classifyLoginError({ name: 'TimeoutError', message: PRIVATE }), 'timeout');
  assert.equal(classifyLoginError({
    name: 'Error', message: 'page.goto: Target page, context or browser has been closed',
  }), 'target-closed');
});

test('unknown errors and lookalike codes cannot forge known transport classifications', () => {
  for (const error of [
    undefined, null, {}, { name: 'Error' },
    { name: 'TimeoutErrorExtra', message: PRIVATE },
    { name: 'Error', message: 'timeout connection refused ' + PRIVATE },
    { name: 'Error', message: 'page.goto: net::ERR_CONNECTION_REFUSED_EXTRA at ' + PRIVATE },
    { name: 'Error', message: 'page.goto: net::ERR_NOT_A_KNOWN_CODE at ' + PRIVATE },
    { name: 'Error', message: 'Target closed' },
    { name: 'Error', message: PRIVATE },
  ]) {
    const result = classifyLoginError(error);
    assert.equal(result, 'other');
    assert.equal(result.includes(PRIVATE), false);
  }
});

test('provider/callback request counters allow only bounded integers', () => {
  for(const key of ['providerSubmitRequests','callbackRequests','postCallbackMeRequests']) {
    for(const value of [0,1,8]) {
      const candidate={...allowed,[key]:value};
      assert.deepEqual(safeMobileLoginObservation(annotate(candidate)),candidate);
    }
    for(const value of [-1,9,0.5,'1',null,[],{},PRIVATE]) {
      expectRejected({...allowed,[key]:value});
    }
  }
});

test('OIDC transport classification discards query tokens and rejects unrelated requests', () => {
  const request=(method,url,navigation=false)=>({
    method:()=>method,url:()=>url,isNavigationRequest:()=>navigation,
  });
  for (const [method,url,expected] of [
    ['POST','http://127.0.0.1:8089/realms/rio-synthetic/login-actions/authenticate?execution='+PRIVATE,'providerSubmit'],
    ['GET','https://localhost:8088/auth/callback?code='+PRIVATE+'&state='+PRIVATE,'callback'],
    ['GET','https://localhost:8088/','document'],
    ['GET','https://localhost:8088/api/me','me'],
    ['GET','https://localhost:8088/api/consent','consent'],
    ['GET','https://localhost:8088/api/me?token='+PRIVATE,null],
    ['GET','https://other.invalid/auth/callback?code='+PRIVATE,null],
    ['GET','http://127.0.0.1:8089/realms/rio-synthetic/login-actions/authenticate',null],
    ['POST','https://localhost:8088/auth/callback?code='+PRIVATE,null],
    ['POST','http://127.0.0.1:8089/realms/other/login-actions/authenticate',null],
    ['GET','https://user:pass@localhost:8088/auth/callback?code='+PRIVATE,null],
    ['GET','https://localhost:8088/auth/callback?code='+PRIVATE+'#secret',null],
  ]) {
    const result=classifyLoginEndpoint(request(method,url,url==='https://localhost:8088/'));
    assert.equal(result,expected);
    assert.equal(String(result).includes(PRIVATE),false);
  }
  assert.equal(classifyLoginEndpoint({method:()=>{throw new Error(PRIVATE)}}),null);
});

test('unknown callback-related fields and sensitive query text are rejected from CI evidence', () => {
  const privateCanary='https://localhost:8088/auth/callback?code='+PRIVATE;
  for (const extra of [
    {callbackUrl:privateCanary},
    {providerPostBody:'username='+PRIVATE},
    {callbackError:'net::ERR_NETWORK_CHANGED '+PRIVATE},
    {OIDCCode:PRIVATE},
  ])expectRejected({...allowed,...extra});
  for (const key of ['providerSubmitStatuses','callbackStatuses']) {
    expectRejected({...allowed,[key]:[privateCanary]});
  }
});

test('cookie presence admits only boolean/null, never a raw bearer', () => {
  for(const value of [true,false,null]){
    const candidate={...allowed,sessionCookiePresentAtFailure:value};
    assert.deepEqual(safeMobileLoginObservation(annotate(candidate)),candidate);
  }
  for(const value of ['true',PRIVATE,1,[],{},undefined]){
    expectRejected({...allowed,sessionCookiePresentAtFailure:value});
  }
});

test('post-callback identity read begins after callback response, not initial 401', async () => {
  const page=new EventEmitter();
  page.url=()=> 'https://localhost:8088/';
  page.context=()=>({cookies:async()=>[{name:'__Host-rio_session',value:PRIVATE}]});
  page.evaluate=async()=>({accountVisible:false,loginButtonVisible:true,feedback:''});
  const observe=observeMobileLogin(page,'alpha');
  const request=(method,url,nav=false)=>({method:()=>method,url:()=>url,isNavigationRequest:()=>nav});
  const respond=(req,status)=>{page.emit('request',req);page.emit('response',{request:()=>req,status:()=>status});};
  const first=request('GET','https://localhost:8088/api/me');
  respond(first,401); // This happens before authentication and is expected.
  const provider=request('POST','http://127.0.0.1:8089/realms/rio-synthetic/login-actions/authenticate?session='+PRIVATE);
  respond(provider,302);
  const callback=request('GET','https://localhost:8088/auth/callback?code='+PRIVATE);
  respond(callback,303);
  const last=request('GET','https://localhost:8088/api/me');
  page.emit('request',last);
  page.emit('requestfailed',last);
  const info={annotations:[]};
  await observe.recordFailure(info,{name:'Error',message:'net::ERR_NETWORK_CHANGED '+PRIVATE});
  observe.stop();
  const result=safeMobileLoginObservation(info.annotations);
  assert.equal(result?.providerSubmitRequests,1);
  assert.deepEqual(result?.providerSubmitStatuses,[302]);
  assert.equal(result?.callbackRequests,1);
  assert.deepEqual(result?.callbackStatuses,[303]);
  assert.deepEqual(result?.meStatuses,[401]);
  assert.equal(result?.postCallbackMeRequests,1);
  assert.deepEqual(result?.postCallbackMeStatuses,[]);
  assert.equal(result?.postCallbackMeRequestFailed,true);
  assert.equal(result?.sessionCookiePresentAtFailure,true);
  assert.equal(result?.errorKind,'network-changed');
  assert.equal(JSON.stringify(result).includes(PRIVATE),false);
  assert.equal(page.listenerCount('request'),0);
});
