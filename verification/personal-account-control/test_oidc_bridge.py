from copy import deepcopy
import unittest
from oidc_bridge import BOUNDARY, assess


class OIDCBridgeTests(unittest.TestCase):
    def setUp(self):
        # Candidate contract fixture, not a captured live OIDC response.
        self.me={'accountId':'TST-alpha','mode':'SYNTHETIC_ONLY',
                 'actorKind':'SYNTHETIC_DEV_ACTOR','credentialControl':'VERIFIED_DEV_OIDC',
                 'operativeAuthority':'NONE','accountActive':False,'canOpenContact':False,
                 'account1':'HOLD','personalAccountControl':deepcopy(BOUNDARY),
                 'csrfToken':'fixture-private-value'}

    def test_known_oidc_identity_still_blocked(self):
        result=assess(self.me)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason'],'STRONG_AUTHENTICATION_EVIDENCE_MISSING')
        self.assertIs(result['activationEligible'],False)

    def test_client_cannot_promote_assurance(self):
        for field,value in [('strongAuthentication','VERIFIED'),('activationEligible',True),('lifecycleAuthority','OWNER')]:
            candidate=deepcopy(self.me)
            candidate['personalAccountControl'][field]=value
            result=assess(candidate)
            self.assertEqual(result['reason'],'UNSUPPORTED_OR_INVALID_METADATA')
            self.assertIs(result['activationEligible'],False)

    def test_wrong_environment_or_actor_blocked(self):
        for field,value in [('accountId','ACCOUNT-1'),('mode','PRODUCTION'),('operativeAuthority','OWNER'),('accountActive',True)]:
            candidate=deepcopy(self.me); candidate[field]=value
            self.assertEqual(assess(candidate)['reason'],'UNSUPPORTED_OR_INVALID_METADATA')

    def test_missing_or_malformed_metadata_never_admits(self):
        for candidate in [None,[],{}, {'personalAccountControl':True}]:
            self.assertEqual(assess(candidate)['status'],'BLOCKED')
        for value in [None,[],{'activationEligible':False}]:
            candidate=deepcopy(self.me); candidate['personalAccountControl']=value
            self.assertEqual(assess(candidate)['reason'],'UNSUPPORTED_OR_INVALID_METADATA')

    def test_unverified_strength_hints_do_not_promote(self):
        self.me.update(amr=['mfa'],acr='strong',reviewApproved=True,role='owner')
        self.assertFalse(assess(self.me)['activationEligible'])

    def test_no_credentials_or_identity_echoed(self):
        result=assess(self.me)
        for value in ['fixture-private-value','TST-alpha','csrfToken']:
            self.assertNotIn(value,str(result))
        self.assertEqual(result['production'],'HOLD')

if __name__=='__main__': unittest.main()
