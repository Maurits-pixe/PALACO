"""Build/check an unsigned review overlay. Never extracts, publishes or deploys."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

from verify import REPO, ROOT, canonical, check as check_evidence, read_json, report_passed, sources, unique

LIMIT=10_000_000


def safe_name(name):
    path=PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '..' not in path.parts and '\\' not in name and not name.endswith('/')


def build(evidence, output):
    with redirect_stdout(io.StringIO()): check_evidence(evidence)
    initial=sources()
    report=read_json(evidence/'evidence.json')
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True,check=True).stdout.strip()
    if report['baseHead']!=head: raise ValueError('base HEAD mismatch')
    changed=subprocess.run(['git','diff','--name-only','HEAD'],cwd=REPO,capture_output=True,text=True,check=True).stdout.splitlines()
    if not set(changed)<=set(initial): raise ValueError('unbound tracked changes')
    files={'source/'+name:(REPO/name).read_bytes() for name in initial}
    for name in ('evidence.json','evidence.sha256'):
        files['evidence/'+name]=(evidence/name).read_bytes()
    manifest={'schema':'pac-review-overlay/v1','baseHead':head,'sources':initial,
        'members':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())},
        'purpose':'REVIEW_CANDIDATE_NOT_RELEASE','production':'HOLD','account1':'HOLD',
        'rioServiceTests':'NOT_EXECUTED','signature':'UNSIGNED_LOCAL_OBSERVATION'}
    if initial!=sources(): raise ValueError('source drift')
    if any(hashlib.sha256(files['source/'+name]).hexdigest()!=digest for name,digest in initial.items()):
        raise ValueError('copy drift')
    # Recheck the copied report, not just the previously read evidence path.
    archived=json.loads(files['evidence/evidence.json'],object_pairs_hook=unique)
    inventory=json.loads(files['source/'+(ROOT/'test-inventory.json').relative_to(REPO).as_posix()])
    if not report_passed(archived,inventory,initial): raise ValueError('copied evidence mismatch')
    if hashlib.sha256(files['evidence/evidence.json']).hexdigest()!=files['evidence/evidence.sha256'].decode().strip():
        raise ValueError('copied evidence digest mismatch')
    files['manifest.json']=canonical(manifest)
    if sum(map(len,files.values()))>LIMIT: raise ValueError('bundle limit')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            if not safe_name(name): raise ValueError('unsafe member')
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            archive.writestr(info,data)
    with output.open('xb') as target: target.write(buffer.getvalue())
    return manifest


def inspect(output):
    with zipfile.ZipFile(output) as archive:
        items=archive.infolist()
        names=[item.filename for item in items]
        if (len(items)>200 or sum(item.file_size for item in items)>LIMIT
            or len(names)!=len(set(names)) or not all(safe_name(n) for n in names)
            or any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in items)):
            raise ValueError('invalid archive members')
        manifest=json.loads(archive.read('manifest.json'),object_pairs_hook=unique)
        if (set(manifest)!={'schema','baseHead','sources','members','purpose','production','account1','rioServiceTests','signature'}
            or manifest['schema']!='pac-review-overlay/v1'
            or manifest['purpose']!='REVIEW_CANDIDATE_NOT_RELEASE'
            or manifest['production']!='HOLD' or manifest['account1']!='HOLD'
            or manifest['rioServiceTests']!='NOT_EXECUTED'
            or manifest['signature']!='UNSIGNED_LOCAL_OBSERVATION'
            or manifest['sources']!=sources()): raise ValueError('manifest mismatch')
        head=subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True,check=True).stdout.strip()
        if manifest['baseHead']!=head: raise ValueError('base HEAD mismatch')
        expected={'source/'+name for name in manifest['sources']}|{'evidence/evidence.json','evidence/evidence.sha256'}
        if set(manifest['members'])!=expected or set(names)!=expected|{'manifest.json'}:
            raise ValueError('member coverage mismatch')
        for name,digest in manifest['members'].items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest: raise ValueError('member digest mismatch')
        for name,digest in manifest['sources'].items():
            if manifest['members']['source/'+name]!=digest: raise ValueError('source manifest mismatch')
        payload=archive.read('evidence/evidence.json')
        if hashlib.sha256(payload).hexdigest()!=archive.read('evidence/evidence.sha256').decode().strip():
            raise ValueError('evidence digest mismatch')
        report=json.loads(payload,object_pairs_hook=unique)
        inventory=json.loads(archive.read('source/'+(ROOT/'test-inventory.json').relative_to(REPO).as_posix()),object_pairs_hook=unique)
        if report['baseHead']!=manifest['baseHead'] or not report_passed(report,inventory,sources()):
            raise ValueError('evidence mismatch')
        return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path)
    group.add_argument('--check',type=Path)
    args=parser.parse_args()
    try:
        if args.output:
            if args.evidence is None: raise ValueError('evidence required')
            build(args.evidence,args.output)
            inspect(args.output)
        else: inspect(args.check)
        print('PAC_REVIEW_OVERLAY CURRENT_SOURCE_MATCH; PRODUCTION HOLD')
        return 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,subprocess.SubprocessError):
        print('PAC_REVIEW_OVERLAY REJECTED')
        return 1


if __name__=='__main__': sys.exit(main())
