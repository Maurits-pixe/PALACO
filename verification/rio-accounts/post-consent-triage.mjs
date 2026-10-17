// Read-only engineering triage. A symptom class is NOT a root-cause claim,
// verification result, diagnosis, authorization or release decision.
import { safePostConsentObservation } from './post-consent-observation.mjs';

export function classifyPostConsentFailure(annotations) {
  const safe=safePostConsentObservation(annotations);
  if (!safe) return {
    accepted:false, symptom:'EVIDENCE_UNUSABLE', next:'RETAIN_RAW_PRIVATE_EVIDENCE_LOCALLY',
    rootCause:'UNKNOWN', decision:'HOLD',
  };
  let symptom='HTTP_UNEXPECTED';
  let next='CHECK_SESSION_BINDING_AND_SERVER_RESPONSE_WITH_INDEPENDENT_EVIDENCE';
  if (safe.accountRequestFailed) {
    symptom='TRANSPORT_FAILURE';
    next='CHECK_BROWSER_AND_NETWORK_EVENT_ORDER_WITH_INDEPENDENT_EVIDENCE';
  } else if (safe.accountStatus===401 || safe.accountStatus===403) {
    symptom='ACCESS_DENIED';
    next='CHECK_ACCOUNT_EPOCH_REVOCATION_AND_COOKIE_SCOPE_WITH_INDEPENDENT_EVIDENCE';
  } else if (safe.accountStatus>=500) {
    symptom='SERVER_RESPONSE_ERROR';
    next='CHECK_BFF_DATABASE_AND_IDP_BOUNDARY_WITH_INDEPENDENT_EVIDENCE';
  } else if (safe.accountStatus>=300 && safe.accountStatus<400) {
    symptom='UNEXPECTED_REDIRECT';
    next='CHECK_ROUTE_AND_AUTHENTICATION_REDIRECT_SEQUENCE_WITH_INDEPENDENT_EVIDENCE';
  }
  return {
    accepted:true,symptom,next,rootCause:'UNKNOWN',decision:'HOLD',
    // This is exclusively known synthetic test metadata: never echo a URL,
    // token, cookie, request body, raw exception or a private account label.
    observed:{stage:safe.stage,accountStatus:safe.accountStatus,
      accountRequestFailed:safe.accountRequestFailed,
      sessionCookiePresent:safe.sessionCookiePresent,
      grantRevision:safe.grantRevision,storedRevision:safe.storedRevision,
      errorKind:safe.errorKind},
  };
}
