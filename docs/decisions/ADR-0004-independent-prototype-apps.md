# ADR-0004: Independent Apps for the PALACO Prototype

- **Status:** Accepted for prototype scope
- **Date:** 2026-10-15
- **Owner:** PALACO
- **Deciders:** Product / Architecture

## Context

The development material describes a central launcher and three modules, but the repository does not contain working AETHER or 5CRIPTIE applications. The current website, launcher, and Bastion preview are separate applications with different implementation stacks. A launcher metadata response can establish only the configured endpoint's response shape and expected app ID; it does not establish authentication, authorization, domain ownership, application safety, or production readiness.

The repository's preview deployments are independently configured. No verified production domain, DNS zone, hosting ownership, or production security review is established by this decision.

## Decision

For the prototype, use **independently deployable apps connected by ordinary HTTPS navigation**:

- The launcher is a routing and endpoint-metadata-checking UI, not an integration or security authority.
- Modules remain separate applications; do not import them as components into the launcher or embed them as if that established trust.
- Each app may retain its current framework. The launcher and Bastion preview use Vue; the public website remains a static, build-free app.
- Treat AETHER and 5CRIPTIE as concepts/placeholders until their application sources and evidence are supplied. Any demo data or generated telemetry must be visibly identified as synthetic.
- Describe launcher success only as **module metadata confirmed** for the configured origin. Do not present it as a security, identity, or authorization verification.

## Boundaries

- This is a prototype architecture decision, not authorization to publish production services or configure DNS.
- Previews must use synthetic data only. Do not enter sensitive information, production credentials, or real operational data.
- A public preview containing sensitive data is **HOLD**. A public HTTPS endpoint, TLS indicator, metadata response, UI label, or test result is not sufficient evidence to lift that hold.
- Claims of secure communications, verified identity, cryptographic safety, live monitoring, or guaranteed deletion require their own implementation evidence and independent review before appearing as established capabilities.
- Production publication remains **NO-GO** until domain/hosting ownership, authentication and authorization, security review, deployment configuration, and operational controls are verified.
- Before adding public hosting, changing DNS, or connecting real-user data, require a separate human-reviewed decision that assesses scope, access controls, data handling, and evidence. This ADR does not authorize those changes.

## Known Limitations

- Independent security review was not completed for this prototype. The review tooling was unavailable, and CodeQL was skipped; security validation therefore remains **UNKNOWN**.
- Runtime authentication, authorization, preview access control, and public exposure have not been independently validated.
- AETHER and 5CRIPTIE are not implemented apps in this repository; their catalog entries are destinations/placeholders, not operational integrations.
- Launcher success checks only the configured origin's metadata response and expected app ID. It does not verify identity, authorization, application behavior, or security.
- Bastion is an isolated local-fixture preview. Its visible tasks, messages, and audit entries are synthetic and are not durable production records.
- No domain ownership, DNS configuration, production hosting, or deployed security-header state is verified by this ADR.
- Passing local tests and builds demonstrates only the tested behavior; it does not establish privacy, cryptographic suitability, or production readiness.

## Consequences

- Mixed frontend frameworks are acceptable while apps are independent; no framework unification is required for this prototype.
- The launcher can be tested without claiming that its destinations are operational.
- Product copy must distinguish a synthetic demo, endpoint reachability, metadata contract confirmation, and security/identity verification.
- Future integration or production deployment requires a separate decision and evidence review.

## Alternatives Considered

1. **One integrated frontend:** deferred; it would require framework and build-system convergence without a current need.
2. **Independent apps with HTTPS navigation:** accepted for the prototype because it preserves boundaries and permits separate preview deployments.

## Related

- [Web preview deployments](../operations/Preview-Deployments.md)
- [ADR-0002: Communication Does Not Imply Authority](ADR-0002-communication-not-authority.md)
