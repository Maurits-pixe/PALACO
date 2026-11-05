// Snapshot conformance model only. Does not verify credentials or issue approvals.
import {canonical,digest,validate,PROFILE,withinValidationWindow} from './value.mjs';
import {prepareConsent} from './client.mjs';
export function checkAdmissionSnapshot(snapshot,context,request,selection) {
 const deny=code=>({status:'REJECTED',code,authorityGranted:false});
 try {
  validate(context,request);canonical(snapshot);canonical(selection);
  if(snapshot.kind!=='SYNTHETIC_ADMISSION_SNAPSHOT_V1')return deny('UNSUPPORTED_SNAPSHOT');
  if(snapshot.timeTrusted!==true||!Number.isSafeInteger(snapshot.now))return deny('TIME_UNVERIFIED');
  const a=snapshot.actor;
  if(!a||a.verified!==true||snapshot.originVerified!==true)return deny('OWNER_AUTH_UNVERIFIED');
  if(a.owner!==context.owner||a.tenant!==context.tenant||a.session!==context.session)return deny('ACTOR_CONTEXT_MISMATCH');
  const cal=snapshot.calendar,g=snapshot.grant,c=snapshot.challenge;
  if(!cal||cal.id!==request.calendarId||cal.owner!==context.owner||cal.tenant!==context.tenant||cal.writeAcl!==true)return deny('CALENDAR_SCOPE');
  if(snapshot.profileAllowed!==true)return deny('POLICY_DENIED');
  if(!g||g.id!==request.grantId||g.calendarId!==request.calendarId||g.owner!==context.owner||g.tenant!==context.tenant||g.session!==context.session||g.generation!==request.generation||g.action!=='CREATE_OWN_EVENT')return deny('GRANT_SCOPE');
  if(g.state!=='ACTIVE')return deny('GRANT_INACTIVE');
  if(g.contractProfile!==PROFILE||g.finishAfterExpiry!==true)return deny('PROFILE_OPT_IN_REQUIRED');
  if(!withinValidationWindow(snapshot.now,g.expiresAt,snapshot.approvalExpiresAt))return deny('SERVER_DEADLINE_EXPIRED');
  const preview=prepareConsent(context,request,{grantExpiresAt:g.expiresAt,approvalExpiresAt:snapshot.approvalExpiresAt});
  if(!c||typeof c.id!=='string'||!c.id||c.state!=='OPEN')return deny('CHALLENGE_NOT_OPEN');
  if(!Number.isSafeInteger(c.expiresAt)||snapshot.now>=c.expiresAt)return deny('CHALLENGE_EXPIRED');
  if(c.contextDigest!==digest(context)||c.requestDigest!==digest(request)||c.previewDigest!==preview.previewDigest)return deny('CHALLENGE_BINDING_MISMATCH');
  if(snapshot.confirmedChallengeId!==c.id||snapshot.confirmedPreviewDigest!==preview.previewDigest||snapshot.confirmedChoices?.approveExactRequest!==true||snapshot.confirmedChoices?.allowLateCompletion!==true)return deny('EXPLICIT_OWNER_CONFIRMATION_REQUIRED');
  if(!selection||selection.kind!=='UNAUTHENTICATED_CONSENT_SELECTION'||selection.status!=='REQUIRES_OWNER_AUTHENTICATION'||selection.contractProfile!==PROFILE||selection.requestDigest!==digest(request)||selection.contextDigest!==digest(context)||selection.previewDigest!==preview.previewDigest)return deny('SELECTION_BINDING_MISMATCH');
  return {status:'SNAPSHOT_REQUIREMENTS_SATISFIED',authorityGranted:false,challengeId:c.id,operationId:request.operationId,approvalId:request.approvalId,requestDigest:digest(request),contextDigest:digest(context),previewDigest:preview.previewDigest};
 }catch {return deny('MALFORMED_INPUT');}
}
