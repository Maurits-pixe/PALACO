"""Refusal-only classifier of candidate RIO metadata, never a session issuer.

Untrusted JSON, including /api/me output, cannot establish identity, MFA or a
mandate here. The current producer advertises UNKNOWN assurance, so no admission
path exists. No tokens, CSRF values or actor details are returned.
"""
BOUNDARY={
    'schema':'rio-personal-account-boundary/v1',
    'strongAuthentication':'UNKNOWN',
    'lifecycleAuthority':'NONE',
    'activationEligible':False,
    'reason':'STRONG_AUTHENTICATION_EVIDENCE_MISSING',
}


def assess(me):
    expected={'mode':'SYNTHETIC_ONLY','actorKind':'SYNTHETIC_DEV_ACTOR',
              'credentialControl':'VERIFIED_DEV_OIDC','operativeAuthority':'NONE',
              'accountActive':False,'canOpenContact':False,'account1':'HOLD'}
    valid=(type(me) is dict and all(type(me.get(k)) is type(v) and me.get(k)==v
                                  for k,v in expected.items())
           and me.get('accountId') in ('TST-alpha','TST-beta')
           and type(me.get('personalAccountControl')) is dict
           and me['personalAccountControl']==BOUNDARY
           and me['personalAccountControl'].get('activationEligible') is False)
    return {'schema':'pac-rio-admission-assessment/v1','status':'BLOCKED',
            'activationEligible':False,'authority':'NONE','production':'HOLD',
            'reason':'STRONG_AUTHENTICATION_EVIDENCE_MISSING' if valid else 'UNSUPPORTED_OR_INVALID_METADATA'}
