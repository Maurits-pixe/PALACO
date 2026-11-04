import json
import unittest

from intake import COOKIE, ORIGIN, FixtureSessions, Intake
from model import Model
from test_model import CHECKS


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.model = Model()
        self.addCleanup(self.model.db.close)
        self.model.seed_fixture_mandates()
        self.model.invite('TST-alpha','fixture-token',0,10)
        self.model.verify('TST-alpha','fixture-token',1,'TST-alpha')
        self.model.stage('TST-alpha',2)
        self.now = 3
        self.sessions = FixtureSessions()
        self.token, self.csrf = self.sessions.seed('TST-reviewer', 30)
        self.adapter = Intake(self.model, self.sessions, lambda: self.now)
        self.headers = [('Origin', ORIGIN), ('Content-Type', 'application/json'),
                        ('Cookie', COOKIE+'='+self.token), ('X-CSRF-Token', self.csrf)]
        self.data = {'account':'TST-alpha', 'revision':1, 'workspace':'synthetic',
                     'scope':'synthetic:read','policy':'staging-v1',
                     'valid_until':20, 'checklist':CHECKS}

    def call(self, data=None, headers=None, raw=None, method='POST', path='/staging/reviews'):
        return self.adapter.handle(method,path,self.headers if headers is None else headers,
            raw if raw is not None else json.dumps(self.data if data is None else data).encode())

    def unchanged(self):
        self.assertEqual(self.model.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')
        self.assertEqual(self.model.db.execute('SELECT COUNT(*) FROM review_evidence').fetchone()[0],0)

    def test_valid_review_binds_actor_and_digest(self):
        status, headers, body = self.call()
        self.assertEqual(status,200)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(body['account1'],'HOLD')
        evidence = self.model.db.execute('SELECT * FROM review_evidence').fetchone()
        self.assertEqual(evidence['reviewer'],'TST-reviewer')
        self.assertEqual(len(evidence['reference']),len('EVD-SYNTHETIC-')+64)
        self.assertEqual(evidence['revision'],1)

    def test_actor_clock_and_environment_injection(self):
        for field, value in [('actor','TST-reviewer'),('now',0),('environment','production'),('strong',True)]:
            with self.subTest(field=field):
                self.assertEqual(self.call({**self.data,field:value})[0],400)
                self.unchanged()

    def test_duplicate_json(self):
        raw = json.dumps(self.data)[:-1] + ',"revision":1}'
        self.assertEqual(self.call(raw=raw.encode())[0],400)
        self.unchanged()

    def test_duplicate_nested_json(self):
        raw = json.dumps(self.data).replace('"purpose": true','"purpose": true, "purpose": true')
        self.assertEqual(self.call(raw=raw.encode())[0],400)
        self.unchanged()

    def test_invalid_json_and_types(self):
        for raw in [b'[]',b'null',b'\xff',b'{',b'{"a":NaN}']:
            with self.subTest(raw=raw):
                self.assertEqual(self.call(raw=raw)[0],400)
                self.unchanged()
        for field,value in [('revision',True),('valid_until',True),('valid_until',304),('checklist',[]),('account',12)]:
            self.assertEqual(self.call({**self.data,field:value})[0],400)
            self.unchanged()

    def test_body_limit(self):
        self.assertEqual(self.call(raw=b'x'*4097)[0],413)
        self.unchanged()

    def test_content_type(self):
        self.assertEqual(self.call(headers=[(k,v) for k,v in self.headers if k!='Content-Type'])[0],415)

    def test_duplicate_header_case_insensitive(self):
        self.assertEqual(self.call(headers=self.headers+[('origin',ORIGIN)])[0],400)
        self.unchanged()

    def test_wrong_origin_and_csrf(self):
        for name,value in [('Origin','https://other.invalid'),('X-CSRF-Token','wrong')]:
            headers = [(k,value if k==name else v) for k,v in self.headers]
            self.assertEqual(self.call(headers=headers)[0],403)
            self.unchanged()

    def test_no_session(self):
        self.assertEqual(self.call(headers=[(k,v) for k,v in self.headers if k!='Cookie'])[0],401)
        self.unchanged()

    def test_expired_session_uses_server_clock(self):
        self.now=30
        self.assertEqual(self.call()[0],401)
        self.unchanged()

    def test_revoked_session(self):
        self.sessions.revoke(self.token)
        self.assertEqual(self.call()[0],401)
        self.unchanged()

    def test_weak_session(self):
        token,csrf=self.sessions.seed('TST-reviewer',30,strong=False)
        headers=[(k,COOKIE+'='+token if k=='Cookie' else csrf if k=='X-CSRF-Token' else v)
                 for k,v in self.headers]
        self.assertEqual(self.call(headers=headers)[0],401)
        self.unchanged()

    def test_wrong_actor_cannot_review(self):
        token,csrf=self.sessions.seed('TST-activator',30)
        headers=[(k,COOKIE+'='+token if k=='Cookie' else csrf if k=='X-CSRF-Token' else v)
                 for k,v in self.headers]
        self.assertEqual(self.call(headers=headers)[0],403)
        self.unchanged()

    def test_cross_workspace(self):
        self.assertEqual(self.call({**self.data,'workspace':'other'})[0],400)
        self.unchanged()

    def test_stale_revision(self):
        self.assertEqual(self.call({**self.data,'revision':2})[0],403)
        self.unchanged()

    def test_stale_policy(self):
        self.model.db.execute("UPDATE policy SET version='staging-v2'")
        self.assertEqual(self.call()[0],403)
        self.unchanged()

    def test_binding_checked_inside_transaction(self):
        original = self.model.review
        def intervening_change(*args, **kwargs):
            self.model.change_scope('TST-alpha','synthetic:read',3)
            return original(*args, **kwargs)
        self.model.review=intervening_change
        self.assertEqual(self.call()[0],403)
        self.unchanged()

    def test_storage_failure_rolls_back_without_echo(self):
        self.model.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'private detail'); END")
        result=self.call()
        self.assertEqual(result[0],503)
        self.assertNotIn('private detail',str(result))
        self.assertNotIn(self.token,str(result))
        self.unchanged()

    def test_routes_and_method(self):
        self.assertEqual(self.call(method='GET')[0],405)
        self.assertEqual(self.call(path='/production/activations')[0],404)
        self.assertEqual(self.call(path='/staging/reviews?actor=TST-reviewer')[0],404)
        self.unchanged()

    def test_activation_with_separate_session_and_replay(self):
        self.assertEqual(self.call()[0],200)
        token,csrf=self.sessions.seed('TST-activator',30)
        headers=[(k,COOKIE+'='+token if k=='Cookie' else csrf if k=='X-CSRF-Token' else v)
                 for k,v in self.headers]
        data={k:v for k,v in self.data.items() if k not in {'checklist','valid_until'}}
        data.update(until=25,key='request-1234')
        self.now=4
        for _ in range(2):
            self.assertEqual(self.call(data,headers,path='/staging/activations')[0],200)
        self.assertEqual(self.model.db.execute("SELECT COUNT(*) FROM audit WHERE current='ACTIVE'").fetchone()[0],1)
        self.model.suspend('TST-alpha',5)
        self.assertEqual(self.call(data,headers,path='/staging/activations')[0],403)
        self.assertFalse(self.model.allowed('TST-alpha','synthetic',5))

if __name__ == '__main__': unittest.main()
