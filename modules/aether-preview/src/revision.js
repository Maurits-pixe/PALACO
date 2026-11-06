// Tracks which input snapshot an asynchronous result belongs to.
// A result may be published only while its originating revision is current.
export function createRevisionGuard() {
  let revision = 0;
  return Object.freeze({
    snapshot: () => revision,
    invalidate: () => { revision += 1; },
    isCurrent: token => token === revision,
  });
}
