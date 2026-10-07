// A closed local demonstration boundary, not a storage capability or D-013 proof.
export const BLOCK_CODE = 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED';
export const MUTATION_PATHS = Object.freeze([
  '/mutations/prepare',
  '/mutations/execute',
  '/api/mutations/prepare',
  '/api/mutations/execute',
]);

export const BLOCK_RESPONSE = Object.freeze({
  status: 'BLOCKED',
  code: BLOCK_CODE,
  scope: 'CURRENT_REQUEST_ONLY',
});

export function isMutationPath(pathname) {
  return MUTATION_PATHS.includes(pathname.replace(/\/$/, ''));
}
