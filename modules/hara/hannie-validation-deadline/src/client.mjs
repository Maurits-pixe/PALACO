// Pure presentation/protocol adapter. No grants, authority, database or network I/O.
import {canonical,digest,exact,validate,PROFILE,RECEIPT_VERSION,withinValidationWindow} from './value.mjs';
const requireThat=(ok,code)=>{if(!ok)throw Error(code);};
const clone=value=>JSON.parse(canonical(value));
const RISK='Deze ene opdracht mag nog worden vastgelegd nadat dit akkoord verloopt, als de laatste controle ervoor geldig was. Daarvoor is geen gegarandeerde maximale vertraging. Intrekken draait een reeds vastgelegde wijziging niet terug.';
export function prepareConsent(context,request,deadlines) {
 validate(context,request);exact(deadlines,['grantExpiresAt','approvalExpiresAt']);
 requireThat([deadlines.grantExpiresAt,deadlines.approvalExpiresAt].every(Number.isSafeInteger),'INVALID_DEADLINE');
 const binding=clone({context,request,deadlines,displayVersion:1});
 return {...binding,previewDigest:digest(binding),heading:'Controleer deze ene agenda-opdracht',actionLabel:'Eigen afspraak aanmaken',title:request.title,riskText:RISK,requiredChoices:['approveExactRequest','allowLateCompletion']};
}
export function recordConsentSelection(preview,choices,selectedAt) {
 const expected=prepareConsent(preview.context,preview.request,preview.deadlines);
 requireThat(canonical(preview)===canonical(expected),'CONSENT_PREVIEW_CHANGED');
 exact(choices,['approveExactRequest','allowLateCompletion']);
 requireThat(choices.approveExactRequest===true&&choices.allowLateCompletion===true,'EXPLICIT_SELECTION_REQUIRED');
 requireThat(withinValidationWindow(selectedAt,preview.deadlines.grantExpiresAt,preview.deadlines.approvalExpiresAt),'CONSENT_SELECTION_EXPIRED');
 return {kind:'UNAUTHENTICATED_CONSENT_SELECTION',status:'REQUIRES_OWNER_AUTHENTICATION',contractProfile:PROFILE,requestDigest:digest(preview.request),contextDigest:digest(preview.context),previewDigest:preview.previewDigest,selectedAt};
}
const RECEIPT_KEYS=['contractProfile','receiptVersion','finishAfterExpiry','operationId','requestDigest','contextDigest','calendarId','eventId','grantId','generation','approvalId','snapshotDigest','grantExpiresAt','approvalExpiresAt','validatedAt','validationMeasurement','timeTrustProfile','auditSequence','durability','durableObservedAt','durabilityMeasurement','exactDurableAt','observedAfterExpiry','deadlineSatisfied'];
export function presentResult(result,context,request) {
 validate(context,request);canonical(result);
 if(result.status==='RESULT_UNKNOWN') {
  requireThat(result.event===undefined&&result.receipt===undefined,'UNEXPECTED_PAYLOAD');
  return {state:'UNKNOWN',heading:'Uitkomst nog niet vastgesteld',explanation:'De uitvoering wordt gecontroleerd. Opnieuw uitvoeren kan een dubbele opdracht veroorzaken.',canAutomaticallyRetry:false};
 }
 if(result.status==='DENIED') {
  requireThat(result.event===undefined&&result.receipt===undefined,'UNEXPECTED_PAYLOAD');
  return {state:'DENIED',heading:'Opdracht niet uitgevoerd',explanation:'Controleer de opdracht en je huidige toestemming voordat je een nieuwe opdracht geeft.',canAutomaticallyRetry:false};
 }
 if(result.status==='COMMITTED_RESULT_WITHHELD') {
  requireThat(result.event===undefined&&result.receipt===undefined,'UNEXPECTED_PAYLOAD');
  requireThat(result.contractProfile===PROFILE&&result.operationId===request.operationId&&Number.isSafeInteger(result.auditSequence)&&result.auditSequence>0,'RESULT_BINDING_MISMATCH');
  return {state:'WITHHELD',heading:'Vastgelegde uitkomst',explanation:result.code==='READ_AUTHORITY_REQUIRED'?'Nieuwe toestemming is nodig om de inhoud te tonen.':'De vastgelegde uitkomst kan nog niet veilig worden getoond. De controle moet eerst worden hersteld.',canAutomaticallyRetry:false};
 }
 requireThat(result.status==='COMMITTED','UNSUPPORTED_RESULT_STATUS');
 const r=result.receipt,e=result.event;
 requireThat(r?.contractProfile===PROFILE&&r?.receiptVersion===RECEIPT_VERSION,'UNSUPPORTED_RECEIPT_PROFILE');
 exact(r,RECEIPT_KEYS);exact(e,['id','calendar_id','revision','title']);
 const expectedEvent={id:request.eventId,calendar_id:request.calendarId,revision:1,title:request.title};
 requireThat(canonical(e)===canonical(expectedEvent),'EVENT_BINDING_MISMATCH');
 requireThat(r.finishAfterExpiry===true&&r.operationId===request.operationId&&r.requestDigest===digest(request)&&r.contextDigest===digest(context)&&r.calendarId===request.calendarId&&r.eventId===request.eventId&&r.grantId===request.grantId&&r.generation===request.generation&&r.approvalId===request.approvalId&&r.snapshotDigest===digest({id:request.eventId,calendarId:request.calendarId,revision:1,title:request.title}),'RECEIPT_BINDING_MISMATCH');
 requireThat(withinValidationWindow(r.validatedAt,r.grantExpiresAt,r.approvalExpiresAt)&&Number.isSafeInteger(r.durableObservedAt)&&r.durableObservedAt>=r.validatedAt&&Number.isSafeInteger(r.auditSequence)&&r.auditSequence>0,'INVALID_RECEIPT_OBSERVATION');
 requireThat(r.validationMeasurement==='PRECOMMIT_VALIDATION_OBSERVATION'&&r.timeTrustProfile==='SYNTHETIC_LIVE_SUPERVISOR_MONOTONE_V1'&&r.durability==='RECONSTRUCTED_COMMIT'&&r.durabilityMeasurement==='READBACK_UPPER_BOUND'&&r.exactDurableAt==='UNKNOWN'&&r.deadlineSatisfied==='VALIDATION_DEADLINE_ONLY'&&r.observedAfterExpiry===(r.durableObservedAt>=Math.min(r.grantExpiresAt,r.approvalExpiresAt)),'UNSUPPORTED_TIME_SEMANTICS');
 requireThat(result.releasePoint==='LOCKED_WORKER_IPC_SEND','UNSUPPORTED_RELEASE_POINT');
 return {state:'CONFIRMED',heading:'Opdracht vastgelegd',title:e.title,explanation:'Je akkoord was geldig bij de laatste controle; de opslag kon later klaar zijn.',timing:r.observedAfterExpiry?'De vastgelegde uitkomst is na verlopen van het schrijfakkoord bevestigd.':'De vastgelegde uitkomst is vóór verlopen van het schrijfakkoord bevestigd.',canAutomaticallyRetry:false};
}
