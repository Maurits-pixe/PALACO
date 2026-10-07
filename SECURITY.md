# Security Policy

GEN-A1 foundation is not a production-security or external-certification
claim. Historical release records do not establish that this checkout is
secure or supported for deployment.

## Reporting

Use GitHub's private vulnerability reporting for
[Maurits-pixe/PALACO](https://github.com/Maurits-pixe/PALACO/security/advisories)
when available, or an established private maintainer contact channel.
Do not publish exploit details, credentials or personal data in a public issue.
No security response deadline or supported-version promise is established here.

## Review boundary

All changes must preserve the constitutional authority boundary, the Genesis
unsafe-code ban, deny lints and prohibition of `Mutex` and `RwLock`.
Review dependency changes, permissions and evidence integrity; never commit
secrets. Record failures and incomplete checks rather than certifying them.

The existing GO-10 audit checks repository policy and workflow configuration.
It is not a RustSec dependency vulnerability audit or proof of runtime
security. Dependency audit and independent review remain separate
certification requirements.
