// Test-only, per-page login observations. No raw exceptions, URLs, cookies or bodies leave this module.
const TYPE = 'rio-mobile-login-observation';
const STAGES = new Set(['initial','opening-bff','landing','starting-oidc','waiting-for-provider',
  'submitting-credentials','waiting-for-bff','waiting-for-account','waiting-for-consent','ready']);
const KINDS = new Set(['unavailable','bff-home','provider','other']);
const ERRORS = new Set(['aborted','connection-refused','connection-reset','connection-closed','empty-response',
  'http2-protocol','tls-certificate','network-changed','timeout','target-closed','other']);
const FEEDBACK = new Set(['unavailable','empty','confirmed','service_unavailable','expired','changed','invalid_response','other']);
const ENDPOINTS = new Set(['document','providerSubmit','callback','me','consent']);
const REQUEST_FAILURE_FIELDS = ['endpoint','errorKind','afterCallbackRedirect'];
const FIELDS = ['actorCase','stage','pageKind','accountVisible','loginButtonVisible','documentStatuses',
  'meStatuses','consentStatuses','providerSubmitStatuses','callbackStatuses',
  'providerSubmitRequests','callbackRequests','postCallbackMeRequests','postCallbackMeStatuses',
  'sessionCookiePresentAtFailure','documentRequestFailed','meRequestFailed','consentRequestFailed',
  'providerSubmitRequestFailed','callbackRequestFailed','postCallbackMeRequestFailed',
  'requestFailures','requestFailuresOverflow','errorKind','feedbackBucket'];
const BFF = 'https://localhost:8088';
const CODE_KIND = new Map([
  ['ERR_ABORTED','aborted'],['ERR_CONNECTION_REFUSED','connection-refused'],['ERR_CONNECTION_RESET','connection-reset'],
  ['ERR_CONNECTION_CLOSED','connection-closed'],['ERR_EMPTY_RESPONSE','empty-response'],['ERR_HTTP2_PROTOCOL_ERROR','http2-protocol'],
  ['ERR_CERT_AUTHORITY_INVALID','tls-certificate'],['ERR_CERT_COMMON_NAME_INVALID','tls-certificate'],
  ['ERR_CERT_DATE_INVALID','tls-certificate'],['ERR_SSL_PROTOCOL_ERROR','tls-certificate'],['ERR_NETWORK_CHANGED','network-changed'],
  ['ERR_TIMED_OUT','timeout'],['ERR_CONNECTION_TIMED_OUT','timeout']
]);
const REQUEST_ERRORS = new Set([...CODE_KIND.values(),'other']);

export function classifyLoginError(error) {
  try {
    if (!error || typeof error !== 'object') return 'other';
    if (error.name === 'TimeoutError') return 'timeout';
    if (typeof error.message !== 'string' || error.message.length > 100000) return 'other';
    const code = /\bnet::(ERR_[A-Z0-9_]+)\b/.exec(error.message)?.[1];
    if (CODE_KIND.has(code)) return CODE_KIND.get(code);
    if (/\bTarget page, context or browser has been closed\b/.test(error.message)) return 'target-closed';
  } catch {}
  return 'other';
}

// Playwright request failures have their own exact-code contract. A helper
// exception can describe a later timeout and must not replace this evidence.
export function classifyRequestFailure(request) {
  try {
    const failure=request.failure();
    if(!failure || typeof failure!=='object' || Array.isArray(failure))return 'other';
    const text=failure.errorText;
    if(typeof text!=='string' || text.length>64)return 'other';
    const match=/^net::(ERR_[A-Z0-9_]+)$/.exec(text);
    if(match && match[0]===text)return CODE_KIND.get(match[1]) ?? 'other';
  } catch {}
  return 'other';
}

export function safeMobileLoginObservation(annotations) {
  if (!Array.isArray(annotations)) return undefined;
  const items=annotations.filter(item=>item?.type===TYPE);
  if (items.length!==1 || typeof items[0].description!=='string' || items[0].description.length>2048) return undefined;
  let value;try { value=JSON.parse(items[0].description); } catch { return undefined; }
  if (!value || typeof value!=='object' || Array.isArray(value)
      || Object.keys(value).length!==FIELDS.length || !FIELDS.every(key=>Object.hasOwn(value,key))
      || !['alpha','beta'].includes(value.actorCase) || !STAGES.has(value.stage) || !KINDS.has(value.pageKind)
      || !ERRORS.has(value.errorKind) || !FEEDBACK.has(value.feedbackBucket)) return undefined;
  for(const key of ['accountVisible','loginButtonVisible','sessionCookiePresentAtFailure']) {
    if(value[key]!==null && typeof value[key]!=='boolean')return undefined;
  }
  for(const key of ['providerSubmitRequests','callbackRequests','postCallbackMeRequests']) {
    if(!Number.isInteger(value[key]) || value[key]<0 || value[key]>8)return undefined;
  }
  for(const key of ['documentRequestFailed','meRequestFailed','consentRequestFailed',
    'providerSubmitRequestFailed','callbackRequestFailed','postCallbackMeRequestFailed','requestFailuresOverflow']) {
    if(typeof value[key]!=='boolean')return undefined;
  }
  if(!Array.isArray(value.requestFailures) || value.requestFailures.length>8)return undefined;
  if(value.requestFailuresOverflow && value.requestFailures.length!==8)return undefined;
  for(const failure of value.requestFailures) {
    if(!failure || typeof failure!=='object' || Array.isArray(failure)
       || Object.keys(failure).length!==REQUEST_FAILURE_FIELDS.length
       || !REQUEST_FAILURE_FIELDS.every(key=>Object.hasOwn(failure,key))
       || !ENDPOINTS.has(failure.endpoint) || !REQUEST_ERRORS.has(failure.errorKind)
       || (failure.afterCallbackRedirect!==null && typeof failure.afterCallbackRedirect!=='boolean'))return undefined;
  }
  for(const key of ['documentStatuses','meStatuses','consentStatuses',
    'providerSubmitStatuses','callbackStatuses','postCallbackMeStatuses']) {
    if(!Array.isArray(value[key]) || value[key].length>8 ||
       value[key].some(n=>!Number.isInteger(n)||n<100||n>599))return undefined;
  }
  return {actorCase:value.actorCase,stage:value.stage,pageKind:value.pageKind,
    accountVisible:value.accountVisible,loginButtonVisible:value.loginButtonVisible,
    documentStatuses:[...value.documentStatuses],meStatuses:[...value.meStatuses],consentStatuses:[...value.consentStatuses],
    providerSubmitStatuses:[...value.providerSubmitStatuses],callbackStatuses:[...value.callbackStatuses],
    providerSubmitRequests:value.providerSubmitRequests,callbackRequests:value.callbackRequests,
    postCallbackMeRequests:value.postCallbackMeRequests,
    postCallbackMeStatuses:[...value.postCallbackMeStatuses],
    sessionCookiePresentAtFailure:value.sessionCookiePresentAtFailure,
    documentRequestFailed:value.documentRequestFailed,meRequestFailed:value.meRequestFailed,
    consentRequestFailed:value.consentRequestFailed,
    providerSubmitRequestFailed:value.providerSubmitRequestFailed,callbackRequestFailed:value.callbackRequestFailed,
    postCallbackMeRequestFailed:value.postCallbackMeRequestFailed,
    requestFailures:value.requestFailures.map(failure=>({endpoint:failure.endpoint,errorKind:failure.errorKind,
      afterCallbackRedirect:failure.afterCallbackRedirect})),
    requestFailuresOverflow:value.requestFailuresOverflow,
    errorKind:value.errorKind,feedbackBucket:value.feedbackBucket};
}

// Classify fixed origin/path/method only. Never emit or store the OAuth code,
// callback query, credentials, request bodies, raw errors, or the URL itself.
export function classifyLoginEndpoint(request) {
  try {
    const url=new URL(request.url()),method=request.method();
    if(url.username || url.password || url.hash)return null;
    if(method==='POST' && url.origin==='http://127.0.0.1:8089' &&
       url.pathname==='/realms/rio-synthetic/login-actions/authenticate')return 'providerSubmit';
    if(method==='GET' && url.origin===BFF && url.pathname==='/auth/callback')return 'callback';
    if(method!=='GET' || url.origin!==BFF || url.search)return null;
    if(url.pathname==='/' && request.isNavigationRequest())return 'document';
    if(url.pathname==='/api/me')return 'me';
    if(url.pathname==='/api/consent')return 'consent';
  } catch {}
  return null;
}
const bucket=text=>{
  if(text==='')return 'empty';
  if(text==='Je toestemming voor deze oefensessie is bevestigd. Persoonlijke toegang blijft gesloten.')return 'confirmed';
  if(text==='RIO is tijdelijk niet beschikbaar. Controleer je testsessie opnieuw.')return 'service_unavailable';
  if(text==='De testsessie is verlopen of niet meer beschikbaar. Meld je opnieuw aan.')return 'expired';
  if(text==='De testsessie is gewijzigd. Controleer je eigen account opnieuw.')return 'changed';
  if(text==='De testsessie kon niet veilig worden gecontroleerd. Probeer opnieuw.')return 'invalid_response';
  return 'other';
};

export function observeMobileLogin(page,actorCase) {
  if(!['alpha','beta'].includes(actorCase))throw new Error('Unsupported synthetic login actor');
  const state={actorCase,stage:'initial',pageKind:'unavailable',accountVisible:null,loginButtonVisible:null,
    documentStatuses:[],meStatuses:[],consentStatuses:[],
    providerSubmitStatuses:[],callbackStatuses:[],postCallbackMeStatuses:[],
    providerSubmitRequests:0,callbackRequests:0,postCallbackMeRequests:0,
    sessionCookiePresentAtFailure:null,
    documentRequestFailed:false,meRequestFailed:false,consentRequestFailed:false,
    providerSubmitRequestFailed:false,callbackRequestFailed:false,
    postCallbackMeRequestFailed:false,
    requestFailures:[],requestFailuresOverflow:false,
    errorKind:'other',feedbackBucket:'unavailable'};
  let stopped=false, recorded=false, callbackRedirectObserved=false;
  const afterCallbackMe=new WeakSet();
  const requestStarts=new WeakMap(), failedRequests=new WeakSet();
  const onRequest=request=>{
    if(stopped)return;
    try {
      if(requestStarts.has(request))return;
      const endpoint=classifyLoginEndpoint(request);
      if(!endpoint)return;
      // Retain only the fixed endpoint and phase at START, never the URL.
      requestStarts.set(request,{endpoint,afterCallbackRedirect:callbackRedirectObserved});
      if(endpoint==='providerSubmit' || endpoint==='callback') {
        const key=endpoint+'Requests';
        state[key]=Math.min(8,state[key]+1);
      }
      // Request must START after the observed callback redirect response,
      // not merely finish later. Initial unauthenticated /api/me stays separate.
      if(endpoint==='me' && callbackRedirectObserved) {
        afterCallbackMe.add(request);
        state.postCallbackMeRequests=Math.min(8,state.postCallbackMeRequests+1);
      }
    } catch {}
  };
  const onResponse=response=>{
    if(stopped)return;
    try {
      const endpoint=classifyLoginEndpoint(response.request()), status=response.status();
      if(endpoint && Number.isInteger(status) && status>=100 && status<=599) {
        const values=state[endpoint+'Statuses'];if(values.length<8)values.push(status);
        if(endpoint==='callback' && status>=300 && status<400)callbackRedirectObserved=true;
        if(endpoint==='me' && afterCallbackMe.has(response.request()) &&
           state.postCallbackMeStatuses.length<8)state.postCallbackMeStatuses.push(status);
      }
    } catch {}
  };
  const onFailed=request=>{
    if(stopped)return;
    try {
      if(failedRequests.has(request))return;
      const start=requestStarts.get(request);
      const endpoint=start?.endpoint ?? classifyLoginEndpoint(request);
      if(!endpoint)return;
      failedRequests.add(request);
      state[endpoint+'RequestFailed']=true;
      if(endpoint==='me' && afterCallbackMe.has(request))state.postCallbackMeRequestFailed=true;
      if(state.requestFailures.length<8) {
        state.requestFailures.push({endpoint,errorKind:classifyRequestFailure(request),
          afterCallbackRedirect:start ? start.afterCallbackRedirect : null});
      } else state.requestFailuresOverflow=true;
    } catch {}
  };
  page.on('request',onRequest);page.on('response',onResponse);page.on('requestfailed',onFailed);
  return {
    setStage(stage) { if(!STAGES.has(stage))throw new Error('Unsupported login observation stage');state.stage=stage; },
    async recordFailure(testInfo,error) {
      if(recorded || stopped)return;recorded=true;
      try {
        state.errorKind=classifyLoginError(error);
        // The boolean contains no cookie value or bearer. If cookie access is
        // unavailable, retain null rather than inventing a negative result.
        try {
          const jar=await page.context().cookies(BFF);
          state.sessionCookiePresentAtFailure=jar.some(cookie=>cookie.name==='__Host-rio_session');
        } catch {}
        try {
          const url=new URL(page.url());
          state.pageKind=url.origin===BFF && url.pathname==='/'?'bff-home':
            url.origin==='http://127.0.0.1:8089' && url.pathname.startsWith('/realms/rio-synthetic/')?'provider':'other';
        } catch {}
        try {
          const snapshot=await Promise.race([
            page.evaluate(()=>{
              const visible=id=>{
                const element=document.getElementById(id);
                return element?Boolean(element.getClientRects().length && getComputedStyle(element).visibility!=='hidden'):null;
              };
              const feedback=document.getElementById('feedback');
              return {accountVisible:visible('account'),loginButtonVisible:visible('start-login'),
                feedback:feedback?feedback.textContent:null};
            }),new Promise(resolve=>setTimeout(()=>resolve(null),500))
          ]);
          if(snapshot) {
            state.accountVisible=snapshot.accountVisible;state.loginButtonVisible=snapshot.loginButtonVisible;
            if(typeof snapshot.feedback==='string')state.feedbackBucket=bucket(snapshot.feedback);
          }
        } catch {}
        const safe=safeMobileLoginObservation([{type:TYPE,description:JSON.stringify(state)}]);
        if(safe && Array.isArray(testInfo?.annotations))testInfo.annotations.push({type:TYPE,description:JSON.stringify(safe)});
      } catch {}
    },
    stop() { stopped=true;page.off('request',onRequest);page.off('response',onResponse);page.off('requestfailed',onFailed); }
  };
}
