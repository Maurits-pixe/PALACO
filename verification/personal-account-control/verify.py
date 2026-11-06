"""Unsigned local evidence runner. No CI, identity or production authority claim."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent.parent
SUITES={'accounts':(ROOT,'test_*.py'),
        'existing_review_gate':(ROOT.parent/'rio-accounts','test_review_gate.py')}
BOUNDARIES={'scope':'SYNTHETIC_ONLY','production':'HOLD','account1':'HOLD',
            'humanApproval':'NOT_VERIFIED','runtimeIntegration':'NOT_EXECUTED',
            'authority':'NONE','signature':'UNSIGNED_LOCAL_OBSERVATION',
            'rioServiceTests':'NOT_EXECUTED'}


def canonical(obj):
    return (json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=True)+'\n').encode()


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate key')
        result[key]=value
    return result


def read_json(path):
    if path.stat().st_size>2_000_000: raise ValueError('size limit')
    return json.loads(path.read_text(),object_pairs_hook=unique)


def sources():
    paths=list(ROOT.glob('*.py'))+list(ROOT.glob('*.md'))+[ROOT/'test-inventory.json']
    paths += [ROOT.parent/'rio-accounts'/p for p in (
        'review_gate.py','test_review_gate.py','review/t04-review-template.json',
        'test_account_readback.mjs','mobile/helpers.mjs','mobile/interaction.spec.mjs',
        'tests/accounts.spec.mjs','durable/durable.spec.mjs')]
    service=REPO/'services'/'rio-accounts'
    paths += [p for p in (service/'src').rglob('*') if p.is_file()]
    paths += list((service/'migrations').glob('*.sql'))
    paths += [service/'Cargo.toml',service/'Cargo.lock']
    paths += [REPO/'.github/workflows/rio-accounts-synthetic.yml']
    result={}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file(): raise ValueError('invalid source')
        result[path.relative_to(REPO).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite): yield from flatten(item)
        else: yield item


def run_suite(name):
    path,pattern=SUITES[name]
    with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
        suite=unittest.defaultTestLoader.discover(str(path),pattern=pattern)
        ids=sorted(test.id() for test in flatten(suite))
        result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    # Never emit exception strings, test output, credentials or local DB files.
    return {'ids':ids,'run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':len(result.skipped),
            'expectedFailures':len(result.expectedFailures),
            'unexpectedSuccesses':len(result.unexpectedSuccesses),
            'successful':result.wasSuccessful()}


def suite_passed(result,expected):
    return (type(result) is dict and set(result)=={
        'ids','run','failures','errors','skipped','expectedFailures','unexpectedSuccesses','successful'}
        and result['ids']==expected and len(expected)==len(set(expected)) and bool(expected)
        and type(result['run']) is int and result['run']==len(expected)
        and all(type(result[k]) is int and result[k]==0 for k in (
            'failures','errors','skipped','expectedFailures','unexpectedSuccesses'))
        and result['successful'] is True)


def report_passed(report,inventory,current):
    return (type(report) is dict and set(report)=={'schema','startedUTC','finishedUTC',
        'python','sqlite','baseHead','boundaries','sources','sourcesStable','suites','status'}
        and report['schema']=='personal-account-local-evidence/v1'
        and report['boundaries']==BOUNDARIES and report['sources']==current
        and report['sourcesStable'] is True and report['status']=='PASS'
        and type(report['suites']) is dict and set(report['suites'])==set(SUITES)
        and set(inventory)==set(SUITES)
        and all(suite_passed(report['suites'][name],inventory[name]) for name in SUITES))


def utc(): return datetime.now(timezone.utc).isoformat()


def execute(output):
    # New directory only: never reuse a stale PASS or replace earlier evidence.
    output.mkdir(parents=True,exist_ok=False)
    started=utc()
    initial=sources()
    inventory=read_json(ROOT/'test-inventory.json')
    results={}
    for name in SUITES:
        try:
            child=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--_suite',name],
                cwd=REPO,capture_output=True,text=True,timeout=60)
            if child.returncode: raise ValueError('suite failed to report')
            results[name]=json.loads(child.stdout,object_pairs_hook=unique)
        except (OSError,ValueError,subprocess.TimeoutExpired):
            results[name]={'infrastructure':'NOT_COMPLETED'}
    final=sources()
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True)
    report={'schema':'personal-account-local-evidence/v1','startedUTC':started,'finishedUTC':utc(),
        'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,
        'baseHead':head.stdout.strip() if head.returncode==0 else 'UNKNOWN',
        'boundaries':BOUNDARIES,'sources':initial,'sourcesStable':initial==final,
        'suites':results,'status':'PASS'}
    if not report_passed(report,inventory,final): report['status']='FAIL'
    payload=canonical(report)
    (output/'evidence.json').write_bytes(payload)
    (output/'evidence.sha256').write_text(hashlib.sha256(payload).hexdigest()+'\n')
    print('PERSONAL_ACCOUNT_LOCAL_EVIDENCE '+report['status'])
    return 0 if report['status']=='PASS' else 1


def check(directory):
    payload=(directory/'evidence.json').read_bytes()
    if hashlib.sha256(payload).hexdigest()!=(directory/'evidence.sha256').read_text().strip():
        raise ValueError('evidence digest mismatch')
    report=read_json(directory/'evidence.json')
    if not report_passed(report,read_json(ROOT/'test-inventory.json'),sources()):
        raise ValueError('evidence does not match passing current sources')
    print('PERSONAL_ACCOUNT_LOCAL_EVIDENCE CURRENT_SOURCE_MATCH')
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path)
    group.add_argument('--check',type=Path)
    group.add_argument('--_suite',choices=SUITES,help=argparse.SUPPRESS)
    args=parser.parse_args()
    try:
        if args._suite:
            print(json.dumps(run_suite(args._suite),sort_keys=True))
            return 0
        return execute(args.output) if args.output else check(args.check)
    except (OSError,ValueError,sqlite3.Error):
        print('PERSONAL_ACCOUNT_LOCAL_EVIDENCE REJECTED')
        return 1


if __name__=='__main__': sys.exit(main())
