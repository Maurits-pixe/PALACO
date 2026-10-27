// Test-only, per-page login observations. No raw exceptions, URLs, cookies or bodies leave this module.
const TYPE = 'rio-mobile-login-observation';
const STAGES = new Set(['initial','opening-bff','landing','starting-oidc','waiting-for-provider',
  'submitting-credentials','waiting-for-bff','waiting-for-account','waiting-for-consent','ready']);
const KINDS = new Set(['unavailable','bff-home','provider','other']);
const ERRORS = new Set(['aborted','connection-refused','connection-reset','connection-closed','empty-response',
  'http2-protocol','tls-certificate','network-changed','timeout','target-closed','other']);
const FEEDBACK = new Set(['unavailable','empty','confirmed','service_unavailable','expired','changed','invalid_response','other']);
const FIELDS = ['actorCase','stage','pageKind','accountVisible','loginButtonVisible','documentStatuses',
  'meStatuses','consentStatuses','documentRequestFailed','meRequestFailed','consentRequestFailed','errorKind','feedbackBucket'];
const BFF = 'https://localhost:8088';
const CODE_KIND = new Map([
  ['ERR_ABORTED','aborted'],['ERR_CONNECTION_REFUSED','connection-refused'],['ERR_CONNECTION_RESET','connection-reset'],
  ['ERR_CONNECTION_CLOSED','connection-closed'],['ERR_EMPTY_RESPONSE','empty-response'],['ERR_HTTP2_PROTOCOL_ERROR','http2-protocol'],
  ['ERR_CERT_AUTHORITY_INVALID','tls-certificate'],['ERR_CERT_COMMON_NAME_INVALID','tls-certificate'],
  ['ERR_CERT_DATE_INVALID','tls-certificate'],['ERR_SSL_PROTOCOL_ERROR','tls-certificate'],['ERR_NETWORK_CHANGED','network-changed'],
  ['ERR_TIMED_OUT','timeout'],['ERR_CONNECTION_TIMED_OUT','timeout']
]);

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

export function safeMobileLoginObservation(annotations) {
  if (!Array.isArray(annotations)) return undefined;
  const items=annotations.filter(item=>item?.type===TYPE);
  if (items.length!==1 || typeof items[0].description!=='string' || items[0].description.length>1024) return undefined;
  let value;try { value=JSON.parse(items[0].description); } catch { return undefined; }
  if (!value || typeof value!=='object' || Array.isArray(value)
      || Object.keys(value).length!==FIELDS.length || !FIELDS.every(key=>Object.hasOwn(value,key))
      || !['alpha','beta'].includes(value.actorCase) || !STAGES.has(value.stage) || !KINDS.has(value.pageKind)
      || !ERRORS.has(value.errorKind) || !FEEDBACK.has(value.feedbackBucket)) return undefined;
  for(const key of ['accountVisible','loginButtonVisible']) {
    if(value[key]!==null && typeof value[key]!=='boolean')return undefined;
  }
  for(const key of ['documentRequestFailed','meRequestFailed','consentRequestFailed']) {
    if(typeof value[key]!=='boolean')return undefined;
  }
  for(const key of ['documentStatuses','meStatuses','consentStatuses']) {
    if(!Array.isArray(value[key]) || value[key].length>8 ||
       value[key].some(n=>!Number.isInteger(n)||n<100||n>599))return undefined;
  }
  return {actorCase:value.actorCase,stage:value.stage,pageKind:value.pageKind,
    accountVisible:value.accountVisible,loginButtonVisible:value.loginButtonVisible,
    documentStatuses:[...value.documentStatuses],meStatuses:[...value.meStatuses],consentStatuses:[...value.consentStatuses],
    documentRequestFailed:value.documentRequestFailed,meRequestFailed:value.meRequestFailed,
    consentRequestFailed:value.consentRequestFailed,errorKind:value.errorKind,feedbackBucket:value.feedbackBucket};
}

function fixedEndpoint(request) {
  try {
    if(request.method()!=='GET')return null;
    const url=new URL(request.url());
    if(url.origin!==BFF || url.search || url.hash)return null;
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
    documentStatuses:[],meStatuses:[],consentStatuses:[],documentRequestFailed:false,meRequestFailed:false,
    consentRequestFailed:false,errorKind:'other',feedbackBucket:'unavailable'};
  let stopped=false, recorded=false;
  const onResponse=response=>{
    if(stopped)return;
    try {
      const endpoint=fixedEndpoint(response.request()), status=response.status();
      if(endpoint && Number.isInteger(status) && status>=100 && status<=599) {
        const values=state[endpoint+'Statuses'];if(values.length<8)values.push(status);
      }
    } catch {}
  };
  const onFailed=request=>{
    if(stopped)return;
    const endpoint=fixedEndpoint(request);
    if(endpoint) state[endpoint+'RequestFailed']=true;
  };
  page.on('response',onResponse);page.on('requestfailed',onFailed);
  return {
    setStage(stage) { if(!STAGES.has(stage))throw new Error('Unsupported login observation stage');state.stage=stage; },
    async recordFailure(testInfo,error) {
      if(recorded || stopped)return;recorded=true;
      try {
        state.errorKind=classifyLoginError(error);
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
    stop() { stopped=true;page.off('response',onResponse);page.off('requestfailed',onFailed); }
  };
}
