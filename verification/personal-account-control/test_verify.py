from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import subprocess
from unittest.mock import patch
import unittest
from verify import BOUNDARIES, SUITES, canonical, read_json, report_passed, suite_passed, check, execute
from pathlib import Path
from tempfile import TemporaryDirectory


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.inventory={name:['test_fixture.Fixed.test_case'] for name in SUITES}
        result={'ids':['test_fixture.Fixed.test_case'],'run':1,'failures':0,'errors':0,
                'skipped':0,'expectedFailures':0,'unexpectedSuccesses':0,'successful':True}
        self.current={'fixture.py':'a'*64}
        self.report={'schema':'personal-account-local-evidence/v1','startedUTC':'fixture',
            'finishedUTC':'fixture','python':'fixture','sqlite':'fixture','baseHead':'fixture',
            'boundaries':deepcopy(BOUNDARIES),'sources':self.current.copy(),'sourcesStable':True,
            'suites':{name:deepcopy(result) for name in SUITES},'status':'PASS'}

    def valid(self): return report_passed(self.report,self.inventory,self.current)

    def test_matching_complete_pass(self): self.assertTrue(self.valid())

    def test_changed_source_rejects_old_evidence(self):
        self.current['fixture.py']='b'*64
        self.assertFalse(self.valid())

    def test_source_changed_during_run(self):
        self.report['sourcesStable']=False
        self.assertFalse(self.valid())

    def test_any_incomplete_or_failing_suite_refused(self):
        for field in ('failures','errors','skipped','expectedFailures','unexpectedSuccesses'):
            report=deepcopy(self.report)
            report['suites']['accounts'][field]=1
            self.assertFalse(report_passed(report,self.inventory,self.current))

    def test_success_flag_alone_is_not_pass(self):
        self.report['suites']['accounts']['run']=0
        self.assertFalse(self.valid())

    def test_missing_test_refused(self):
        self.report['suites']['accounts']['ids']=[]
        self.assertFalse(self.valid())

    def test_duplicate_test_refused(self):
        result=deepcopy(self.report['suites']['accounts'])
        result['ids']*=2; result['run']=2
        self.assertFalse(suite_passed(result,result['ids']))

    def test_missing_suite_refused(self):
        del self.report['suites']['existing_review_gate']
        self.assertFalse(self.valid())

    def test_authority_promotion_refused(self):
        self.report['boundaries']['production']='GO'
        self.assertFalse(self.valid())

    def test_failed_report_refused(self):
        self.report['status']='FAIL'
        self.assertFalse(self.valid())

    def test_duplicate_json_keys_refused(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'record.json'
            path.write_text('{"status":"FAIL","status":"PASS"}')
            with self.assertRaises(ValueError): read_json(path)

    def test_artifact_tamper_refused(self):
        with TemporaryDirectory() as tmp:
            directory=Path(tmp)
            payload=b'{"status":"FAIL"}'
            (directory/'evidence.json').write_bytes(payload)
            (directory/'evidence.sha256').write_text(hashlib.sha256(payload).hexdigest())
            (directory/'evidence.json').write_bytes(b'{"status":"PASS"}')
            with self.assertRaises(ValueError): check(directory)

    def test_existing_evidence_directory_never_overwritten(self):
        with TemporaryDirectory() as tmp:
            directory=Path(tmp)
            marker=directory/'evidence.json'
            marker.write_bytes(b'original')
            with self.assertRaises(FileExistsError): execute(directory)
            self.assertEqual(marker.read_bytes(),b'original')

    def test_timeout_emits_fail_not_stale_pass(self):
        def child(args,**kwargs):
            if '--_suite' in args: raise subprocess.TimeoutExpired('fixture',60)
            return subprocess.CompletedProcess(args,0,stdout='fixture-base',stderr='')
        with TemporaryDirectory() as tmp:
            directory=Path(tmp)/'new-evidence'
            with patch('verify.subprocess.run',side_effect=child),redirect_stdout(io.StringIO()):
                self.assertEqual(execute(directory),1)
            report=read_json(directory/'evidence.json')
            self.assertEqual(report['status'],'FAIL')
            self.assertTrue(all(s=={'infrastructure':'NOT_COMPLETED'} for s in report['suites'].values()))

    def test_canonical_serialization_stable(self):
        self.assertEqual(canonical({'b':1,'a':2}),canonical({'a':2,'b':1}))

if __name__=='__main__': unittest.main()
