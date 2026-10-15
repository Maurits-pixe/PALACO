import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { classifyLoginEndpoint, classifyLoginError, classifyRequestFailure, observeMobileLogin, safeMobileLoginObservation } from './login-observation.mjs';
import SafeReporter from './safe-reporter.mjs';

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
  requestFailures: [{ endpoint: 'callback', errorKind: 'connection-reset', afterCallbackRedirect: false }],
  requestFailuresOverflow: false,
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
  first.requestFailures[0].endpoint = 'me';
  first.requestFailures.push({ endpoint: 'document', errorKind: 'other', afterCallbackRedirect: null });
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
  assert.ok(serialized.length < 2048);
  const boundary = serialized + ' '.repeat(2048 - serialized.length);
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

const failureRecord = (endpoint='me', errorKind='connection-reset', afterCallbackRedirect=false) =>
  ({endpoint,errorKind,afterCallbackRedirect});

test('request failure records require exact enums, nullable phase, bounded length and overflow', () => {
  for(const endpoint of ['document','providerSubmit','callback','me','consent']) {
    for(const afterCallbackRedirect of [false,true,null]) {
      const candidate={...allowed,requestFailures:[failureRecord(endpoint,'other',afterCallbackRedirect)]};
      assert.deepEqual(safeMobileLoginObservation(annotate(candidate)),candidate);
    }
  }
  for(const errorKind of ['aborted','connection-refused','connection-reset','connection-closed',
    'empty-response','http2-protocol','tls-certificate','network-changed','timeout','other']) {
    const candidate={...allowed,requestFailures:[failureRecord('callback',errorKind)]};
    assert.deepEqual(safeMobileLoginObservation(annotate(candidate)),candidate);
  }
  for(const requestFailures of [null,{},'failed',Array(9).fill(failureRecord()),
    [null],[[]],[{}],[failureRecord(PRIVATE)],
    [failureRecord('me',PRIVATE)],[failureRecord('me','target-closed')],
    [failureRecord('me','other',0)],[failureRecord('me','other','true')]]) {
    expectRejected({...allowed,requestFailures});
  }
  for(const key of ['endpoint','errorKind','afterCallbackRedirect']) {
    const record=failureRecord();delete record[key];
    expectRejected({...allowed,requestFailures:[record]});
  }
  for(const extra of ['url','query','cookie','rawError','body','code','password','__proto__']) {
    expectRejected({...allowed,requestFailures:[{...failureRecord(),[extra]:PRIVATE}]});
  }
  for(const requestFailuresOverflow of [null,0,'false',PRIVATE]) {
    expectRejected({...allowed,requestFailuresOverflow});
  }
  expectRejected({...allowed,requestFailuresOverflow:true});
  const saturated={...allowed,requestFailures:Array.from({length:8},()=>failureRecord()),requestFailuresOverflow:true};
  assert.deepEqual(safeMobileLoginObservation(annotate(saturated)),saturated);
});

test('maximum admitted diagnostic fields fit the fixed 2048 limit without truncation', () => {
  const maximum={...allowed,stage:'submitting-credentials',feedbackBucket:'service_unavailable',
    requestFailures:Array.from({length:8},()=>failureRecord('providerSubmit','connection-refused',false)),
    requestFailuresOverflow:true};
  for(const key of ['documentStatuses','meStatuses','consentStatuses','providerSubmitStatuses',
    'callbackStatuses','postCallbackMeStatuses'])maximum[key]=Array(8).fill(599);
  const serialized=JSON.stringify(maximum);
  assert.ok(serialized.length<2048);
  assert.deepEqual(safeMobileLoginObservation(annotate(serialized.padEnd(2048))),maximum);
  assert.equal(safeMobileLoginObservation(annotate(serialized.padEnd(2049))),undefined);
});

test('request failure codes are exact and independent of helper exception parsing', () => {
  for(const [code,kind] of [
    ['ERR_ABORTED','aborted'],['ERR_CONNECTION_REFUSED','connection-refused'],
    ['ERR_CONNECTION_RESET','connection-reset'],['ERR_CONNECTION_CLOSED','connection-closed'],
    ['ERR_EMPTY_RESPONSE','empty-response'],['ERR_HTTP2_PROTOCOL_ERROR','http2-protocol'],
    ['ERR_CERT_AUTHORITY_INVALID','tls-certificate'],['ERR_CERT_COMMON_NAME_INVALID','tls-certificate'],
    ['ERR_CERT_DATE_INVALID','tls-certificate'],['ERR_SSL_PROTOCOL_ERROR','tls-certificate'],
    ['ERR_NETWORK_CHANGED','network-changed'],['ERR_TIMED_OUT','timeout'],['ERR_CONNECTION_TIMED_OUT','timeout'],
  ])assert.equal(classifyRequestFailure({failure:()=>({errorText:'net::'+code})}),kind);
  for(const errorText of [null,undefined,17,{},[],PRIVATE,
    'ERR_NETWORK_CHANGED','net::ERR_NETWORK_CHANGED_EXTRA','net::ERR_UNKNOWN',
    'net::ERR_NETWORK_CHANGED '+PRIVATE,'prefix net::ERR_NETWORK_CHANGED',
    'net::ERR_NETWORK_CHANGED\n',' net::ERR_NETWORK_CHANGED','net::ERR_NETWORK_CHANGED'.repeat(10)]) {
    assert.equal(classifyRequestFailure({failure:()=>({errorText})}),'other');
  }
  for(const request of [null,{}, {failure:()=>null},
    {failure:()=>{throw Error(PRIVATE);}},
    {get failure(){throw Error(PRIVATE);}},
    {failure:()=>({get errorText(){throw Error(PRIVATE);}})}]) {
    assert.equal(classifyRequestFailure(request),'other');
  }
});

function observedPage() {
  const page=new EventEmitter();
  page.url=()=> 'https://localhost:8088/';
  page.context=()=>({cookies:async()=>[]});
  page.evaluate=async()=>({accountVisible:false,loginButtonVisible:true,feedback:''});
  return page;
}
function requestWithFailure(url,errorText='net::ERR_NETWORK_CHANGED',method='GET',nav=false) {
  return {url:()=>url,method:()=>method,isNavigationRequest:()=>nav,failure:()=>({errorText})};
}
function callbackRedirect(page) {
  const request=requestWithFailure('https://localhost:8088/auth/callback?code='+PRIVATE);
  page.emit('request',request);
  page.emit('response',{request:()=>request,status:()=>303});
}
async function failureSnapshot(observation,error={name:'TimeoutError',message:PRIVATE}) {
  const info={annotations:[]};
  await observation.recordFailure(info,error);
  observation.stop();
  const result=safeMobileLoginObservation(info.annotations);
  assert.ok(result);
  assert.equal(JSON.stringify(result).includes(PRIVATE),false);
  return result;
}

test('request start phase survives late failures and helper timeout independently', async () => {
  const page=observedPage(),observation=observeMobileLogin(page,'alpha');
  const early=requestWithFailure('https://localhost:8088/api/me','net::ERR_CONNECTION_RESET');
  page.emit('request',early);
  callbackRedirect(page);
  page.emit('request',early); // Duplicate notification cannot move an earlier start forward.
  page.emit('requestfailed',early);
  const document=requestWithFailure('https://localhost:8088/','net::ERR_NETWORK_CHANGED','GET',true);
  const me=requestWithFailure('https://localhost:8088/api/me','net::ERR_CONNECTION_REFUSED');
  for(const request of [document,me]) {page.emit('request',request);page.emit('requestfailed',request);}
  const result=await failureSnapshot(observation);
  assert.equal(result.errorKind,'timeout');
  assert.deepEqual(result.requestFailures,[failureRecord('me','connection-reset',false),
    failureRecord('document','network-changed',true),failureRecord('me','connection-refused',true)]);
  assert.equal(result.postCallbackMeRequests,1);
  assert.equal(result.postCallbackMeRequestFailed,true);
  assert.deepEqual(result.callbackStatuses,[303]);
});

test('missing request start remains unknown and cached endpoint cannot change at failure', async () => {
  const page=observedPage(),observation=observeMobileLogin(page,'beta');
  const callback=requestWithFailure('https://localhost:8088/auth/callback?code='+PRIVATE);
  page.emit('request',callback);
  callback.url=()=> 'https://unrelated.invalid/?secret='+PRIVATE;
  page.emit('requestfailed',callback);
  callbackRedirect(page);
  page.emit('requestfailed',requestWithFailure('https://localhost:8088/api/me'));
  const result=await failureSnapshot(observation);
  assert.deepEqual(result.requestFailures,[failureRecord('callback','network-changed',false),
    failureRecord('me','network-changed',null)]);
  assert.equal(result.postCallbackMeRequestFailed,false);
  assert.equal(result.postCallbackMeRequests,0);
});

test('distinct failures are bounded, deduplicated and ignore unknown endpoints', async () => {
  const page=observedPage(),observation=observeMobileLogin(page,'alpha');
  for(let i=0;i<10;i++)page.emit('requestfailed',requestWithFailure('https://unrelated.invalid/?code='+PRIVATE));
  const first=requestWithFailure('https://localhost:8088/api/consent');
  page.emit('request',first);page.emit('requestfailed',first);
  for(let i=0;i<10;i++)page.emit('requestfailed',first);
  for(let i=0;i<8;i++) {
    const request=requestWithFailure('https://localhost:8088/api/me');
    page.emit('request',request);page.emit('requestfailed',request);
  }
  const result=await failureSnapshot(observation);
  assert.equal(result.requestFailures.length,8);
  assert.deepEqual(result.requestFailures,[failureRecord('consent','network-changed',false),
    ...Array.from({length:7},()=>failureRecord('me','network-changed',false))]);
  assert.equal(result.requestFailuresOverflow,true);
});

test('successful observers emit nothing and stopped observers detach all listeners', async () => {
  const page=observedPage(),observation=observeMobileLogin(page,'alpha'),info={annotations:[]};
  page.emit('requestfailed',null);
  page.emit('request',17);
  observation.stop();observation.stop();
  page.emit('requestfailed',requestWithFailure('https://localhost:8088/api/me'));
  await observation.recordFailure(info,{name:'TimeoutError',message:PRIVATE});
  assert.deepEqual(info.annotations,[]);
  for(const event of ['request','response','requestfailed'])assert.equal(page.listenerCount(event),0);
});

test('mobile reporter emits only validated nested request failures on failed cases', () => {
  const original=process.stdout.write;
  let output='';process.stdout.write=chunk=>{output+=String(chunk);return true;};
  try {
    const reporter=new SafeReporter({mobileVerification:true});
    const item=annotations=>({title:'[RIO-MOBILE-01] '+PRIVATE,annotations,
      parent:{project:()=>({name:'android-emulation'})}});
    const result={status:'failed',duration:1,steps:[],errors:[{message:PRIVATE}]};
    reporter.onTestEnd(item(annotate(allowed)),result);
    assert.deepEqual(reporter.results[0].loginObservation,allowed);
    reporter.onTestEnd(item(annotate({...allowed,requestFailures:[{...failureRecord(),url:PRIVATE}]})),result);
    assert.equal(reporter.results[1].loginObservation,undefined);
    reporter.onTestEnd(item(annotate(allowed)),{...result,status:'passed'});
    assert.equal(Object.hasOwn(reporter.results[2],'loginObservation'),false);
    assert.equal(JSON.stringify(reporter.results).includes(PRIVATE),false);
    assert.equal(output.includes(PRIVATE),false);
  } finally {process.stdout.write=original;}
});
