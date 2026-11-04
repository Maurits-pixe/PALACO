// This suite has 20 required controls. A filtered or truncated run is not proof.
export function evidencePassed({compile, run, counts, sourceUnchanged, commit}) {
  return compile.status === 0 && !compile.error && !compile.signal &&
    run.status === 0 && !run.error && !run.signal &&
    counts.tests === 20 && counts.pass === 20 &&
    ['fail', 'cancelled', 'skipped', 'todo'].every(k => counts[k] === 0) &&
    sourceUnchanged === true && commit.status === 0 && !commit.error &&
    !commit.signal && /^[a-f0-9]{40}$/.test(commit.stdout.trim());
}
