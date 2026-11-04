"""Disposable integrated SYNTHETIC rehearsal. No socket or RIO runtime wiring."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from intake import COOKIE, ORIGIN, CHECKS, FixtureSessions, Intake
from model import Model, Denied
from restart import RestartGuard
from safety import GuardedModel, SafetyStore

ROLES={'TST-boot-reviewer':'review_boot','TST-boot-approver':'approve_boot'}


class Rehearsal:
    def __init__(self, directory):
        self.now=3
        self.model=Model(str(Path(directory)/'accounts.sqlite'))
        self.safety=SafetyStore(str(Path(directory)/'safety.sqlite'))
        self.model.seed_fixture_mandates()
        self.safety.fixture_provision_once()
        self.model.invite('TST-alpha','synthetic-rehearsal-token',0,10)
        self.model.verify('TST-alpha','synthetic-rehearsal-token',1,'TST-alpha')
        self.model.stage('TST-alpha',2)
        self.guarded=GuardedModel(self.model,self.safety)
        self.sessions=FixtureSessions()
        self.credentials={actor:self.sessions.seed(actor,25) for actor in ('TST-reviewer','TST-activator')}
        self.restart()

    def close(self):
        self.model.db.close()
        self.safety.db.close()

    def restart(self):
        # New fence instance, not a claim of process or service restart.
        self.runtime=RestartGuard(self.guarded,lambda:self.now,ROLES)
        self.intake=Intake(self.runtime,self.sessions,lambda:self.now)

    def approve_start(self):
        record=self.runtime.review_boot('TST-boot-reviewer',valid_until=self.now+20)
        self.runtime.approve_boot('TST-boot-approver',record)

    def request(self, action, actor=None, **changes):
        actor=actor or ('TST-reviewer' if action=='reviews' else 'TST-activator')
        token,csrf=self.credentials[actor]
        headers=[('Origin',ORIGIN),('Content-Type','application/json'),
                 ('Cookie',COOKIE+'='+token),('X-CSRF-Token',csrf)]
        body={'account':'TST-alpha','revision':1,'workspace':'synthetic',
              'scope':'synthetic:read','policy':'staging-v1'}
        if action=='reviews': body.update(valid_until=24,checklist=dict.fromkeys(CHECKS,True))
        else: body.update(until=24,key='rehearsal-request-1')
        body.update(changes)
        return self.intake.handle('POST','/staging/'+action,headers,json.dumps(body).encode())

    def active(self): return self.runtime.allowed('TST-alpha','synthetic')


def run():
    with TemporaryDirectory(prefix='pac-synthetic-') as directory:
        fixture=Rehearsal(directory)
        try:
            checks={}
            checks['startup_review_denied']=fixture.request('reviews')[0]==403
            checks['startup_has_no_access']=not fixture.active()
            fixture.approve_start()
            checks['review_recorded']=fixture.request('reviews')[0]==200
            checks['review_alone_has_no_access']=not fixture.active()
            checks['wrong_actor_cannot_activate']=fixture.request('activations',actor='TST-reviewer')[0]==403
            checks['activation_recorded']=fixture.request('activations')[0]==200
            checks['synthetic_access_granted']=fixture.active()
            fixture.restart()
            checks['fresh_fence_denies_existing_active_account']=not fixture.active()
            fixture.approve_start()
            checks['fresh_review_restores_only_existing_synthetic_access']=fixture.active()
            fixture.model.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'injected'); END")
            checks['suspension_audit_pending']=fixture.runtime.suspend('TST-alpha',fixture.now)=='AUDIT_PENDING'
            checks['suspension_blocks_access']=not fixture.active()
            checks['suspension_blocks_replay']=fixture.request('activations')[0]==403
            fixture.restart()
            try:
                fixture.approve_start()
                checks['pending_audit_blocks_start']=False
            except Denied as refusal:
                checks['pending_audit_blocks_start']=str(refusal)=='AUDIT_RECONCILIATION_REQUIRED'
            fixture.model.db.execute('DROP TRIGGER fail_audit')
            pending=fixture.model.pending_suspensions()
            checks['audit_reconciled']=len(pending)==1 and fixture.model.deliver_suspension(pending[0]['id'])=='AUDIT_DELIVERED'
            fixture.approve_start()
            checks['reconciliation_does_not_restore_account']=not fixture.active()
            return {'schema':'pac-integrated-rehearsal/v1','scope':'SYNTHETIC_ONLY',
                    'production':'HOLD','account1':'HOLD','humanApproval':'NOT_VERIFIED',
                    'rioRuntimeIntegration':'NOT_EXECUTED','checks':checks,
                    'status':'PASS' if all(checks.values()) else 'FAIL'}
        finally: fixture.close()


if __name__=='__main__':
    result=run()
    print(json.dumps(result,sort_keys=True,indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 1)
