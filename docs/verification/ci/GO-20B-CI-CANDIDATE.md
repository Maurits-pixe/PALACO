GO-20B CI integration candidate — NOT ACTIVE / NOT EXECUTED

The companion YAML is reviewable text outside .github/workflows. It has not
been installed, dispatched, or run. Local verifier evidence does not prove
this CI workflow. It asserts no merge authority or canonical ascension.

Proposed trigger: workflow_dispatch only. The job guard permits only repository
Maurits-pixe/PALACO and refs/heads/go-18/write-authorization-proof. Main cannot
run this job. Permissions are contents: read; no remote write operation occurs.

Runner: ubuntu-24.04, complete checkout, complete Git history, Python 3.12.
Linux retains historical names that Windows cannot materialize exactly.
The actual Python patch version, runner image version, platform and Git version
are recorded rather than assumed.

Before executing the verifier, the workflow verifies the exact dispatched
commit, a clean checkout, current origin/main, fetched main commit and tree,
and verifier blob identity. It creates local main only when absent and only
from the matching fetched ref; it never overwrites an existing local main.
The baseline remains commit 96864384022191e7e6f6fd59134defbd3ae41151 with tree
da01553abfc4d07865b76cb99a13addd2477d4d3. It requires the repaired candidate
verifier/spec that distinguish those two Git objects.

Exact verifier stdout, stderr and exit code, commit/tree/blob identities,
runtime and UTC times are retained outside the checkout. Preparation failure
is recorded as BLOCKED / NOT_RUN instead of PASS. Upload is attempted with
always(), including failed execution. Like all workflows, abrupt runner loss
or artifact-service failure can prevent artifact availability; the job log
remains the additional record. Live origin/main is checked again afterward.

Action provenance:
- actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 is already pinned in
  .github/workflows/go-07-pvs-001.yml and other GO workflows.
- actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 is already pinned
  in .github/workflows/go-13-standards-conformance.yml.
- Existing repository upload-artifact uses were mutable @v4 references.
  The official actions/upload-artifact v4 Git ref was read on 2026-10-07:
  https://api.github.com/repos/actions/upload-artifact/git/ref/tags/v4
  It resolved directly to commit ea165f8d65b6e75b540449e92b4886f43607fa02.
  The candidate uses that immutable commit, not the mutable tag.

Activation and dispatch remain separate future actions. GitHub documentation
states workflow_dispatch needs the workflow file on the default branch to
trigger, with branch dispatch possible after initial workflow registration/run.
Source checked 2026-10-07:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch
This newly drafted workflow has no such registration or prior run. It is not
currently dispatchable merely by placing it on the working branch. This draft
does not work around that constraint or authorize any main change. Future
activation planning must respect the existing no-main, no-merge boundary.
