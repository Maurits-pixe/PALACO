export function validRequestReferences(assessmentId, requestDigest) {
  return typeof assessmentId === 'string'
    && assessmentId.length >= 1 && assessmentId.length <= 128
    && !/[^A-Za-z0-9._:-]/.test(assessmentId)
    && typeof requestDigest === 'string' && requestDigest.length === 64
    && !/[^a-f0-9]/.test(requestDigest);
}
