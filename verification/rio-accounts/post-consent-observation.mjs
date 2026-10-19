// Failure-only synthetic consent/account-read evidence. No cookies, token,
// URL, account identity, full receipt or raw error may enter this report.
import { classifyLoginError } from './login-observation.mjs';

export const POST_CONSENT_TYPE = 'rio-mobile-post-consent-read';
const ERROR_KINDS = new Set([
  'other','aborted','connection-refused','connection-reset','connection-closed',
  'empty-response','http2-protocol','tls-certificate','network-changed',
  'timeout','target-closed',
]);
const KEYS = ['stage','grantRevision','storedRevision','accountStatus',
  'accountRequestFailed','sessionCookiePresent','errorKind'];

export function safePostConsentObservation(annotations) {
  if (!Array.isArray(annotations)) return undefined;
  const entries=annotations.filter(entry=>entry?.type===POST_CONSENT_TYPE);
  if(entries.length!==1 || typeof entries[0]?.description!=='string' ||
     entries[0].description.length>512)return undefined;
  let item;
  try { item=JSON.parse(entries[0].description); }catch{return undefined;}
  if(!item || Array.isArray(item) || typeof item!=='object' ||
     Object.keys(item).length!==KEYS.length ||
     !KEYS.every(key=>Object.hasOwn(item,key)) ||
     item.stage!=='after-grant' || !ERROR_KINDS.has(item.errorKind) ||
     typeof item.accountRequestFailed!=='boolean' ||
     !(item.sessionCookiePresent===null || typeof item.sessionCookiePresent==='boolean') ||
     !(item.accountStatus===null ||
       (Number.isInteger(item.accountStatus) && item.accountStatus>=100 && item.accountStatus<=599)) ||
     (item.accountRequestFailed && item.accountStatus!==null))return undefined;
  for(const key of ['grantRevision','storedRevision']){
    if(!Number.isSafeInteger(item[key]) || item[key]<0 || item[key]>1000000000)return undefined;
  }
  // Only emit actual failures: no record should claim an ordinary successful 200.
  if(item.accountStatus===200 || (!item.accountRequestFailed && item.accountStatus===null))return undefined;
  return Object.fromEntries(KEYS.map(key=>[key,item[key]]));
}

export async function recordPostConsentFailure(page,testInfo,details) {
  const observation={
    stage:'after-grant',
    grantRevision:details.grantRevision,
    storedRevision:details.storedRevision,
    accountStatus:details.accountStatus,
    accountRequestFailed:details.accountRequestFailed,
    sessionCookiePresent:null,
    errorKind:details.errorKind,
  };
  try {
    // Inspect only whether a valid-named cookie exists. Never read/serialize its
    // value or headers and never request the account endpoint a second time.
    const jar=await page.context().cookies('https://localhost:8088');
    observation.sessionCookiePresent=jar.some(cookie=>cookie.name==='__Host-rio_session');
  } catch {}
  const safe=safePostConsentObservation([{
    type:POST_CONSENT_TYPE,description:JSON.stringify(observation),
  }]);
  if(safe && Array.isArray(testInfo?.annotations))testInfo.annotations.push({
    type:POST_CONSENT_TYPE,description:JSON.stringify(safe),
  });
}

// Exactly one existing own-account read. No retry or weaker status checks.
// The caller still asserts HTTP 200, actor isolation and account HOLD.
export async function postConsentOwnAccountRead(page,testInfo,revisions,readOwnAccount) {
  let response;
  try { response=await readOwnAccount(page); }
  catch(error){
    await recordPostConsentFailure(page,testInfo,{
      grantRevision:revisions.grantRevision,storedRevision:revisions.storedRevision,
      accountStatus:null,accountRequestFailed:true,errorKind:classifyLoginError(error),
    });
    throw error;
  }
  if(response?.status!==200)await recordPostConsentFailure(page,testInfo,{
    grantRevision:revisions.grantRevision,storedRevision:revisions.storedRevision,
    accountStatus:response?.status??null,accountRequestFailed:false,errorKind:'other',
  });
  return response;
}
