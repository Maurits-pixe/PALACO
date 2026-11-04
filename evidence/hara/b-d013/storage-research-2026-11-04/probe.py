"""Isolated synthetic SQLite cancellation probe, not a D-013 adapter."""
import hashlib, json, os, pathlib, signal, sqlite3, subprocess, sys, tempfile, threading, time
ROOT=pathlib.Path(__file__).resolve().parent
now=lambda:time.time_ns()//1_000_000

def writer(directory, policy, expired):
    folder=pathlib.Path(directory); db=sqlite3.connect(folder/'probe.db')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('BEGIN IMMEDIATE');db.execute("INSERT INTO effects VALUES ('synthetic')")
    expiry=now()+(-1 if expired else 250)
    samples=[]; interrupted=[];stop=threading.Event()
    if policy in ('progress','both'):
        def progress():
            stamp=now();samples.append(stamp);return int(stamp>=expiry)
        db.set_progress_handler(progress,1)
    if policy in ('interrupt','both'):
        def watchdog():
            while not stop.wait(.001):
                if now()>=expiry:
                    interrupted.append(now());db.interrupt();return
        threading.Thread(target=watchdog,daemon=True).start()
    if os.environ.get('B013_WAL_ARM'):
        pathlib.Path(os.environ['B013_WAL_ARM']).write_text('armed')
    entered=now();error=None
    try:db.commit()
    except sqlite3.Error as exc:error={'type':type(exc).__name__,'text':str(exc)}
    returned=now();stop.set()
    # Preserve the API outcome before abrupt death; no close, checkpoint, cleanup or replay.
    (folder/'writer.json').write_text(json.dumps({'sqlite':sqlite3.sqlite_version,'expiry':expiry,'commitEnteredAt':entered,'commitReturnedAt':returned,'error':error,'progressSamples':samples,'interruptSamples':interrupted}))
    os.kill(os.getpid(),signal.SIGKILL)

if len(sys.argv)>1 and sys.argv[1]=='writer':
    writer(sys.argv[2],sys.argv[3],sys.argv[4]=='expired')
else:
    library=ROOT/'stall.so'; out=ROOT/'results';out.mkdir(exist_ok=True)
    compiled=subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Werror','-o',str(library),str(ROOT/'wal-stall.c'),'-ldl'],capture_output=True,text=True)
    (out/'compiler.stderr').write_text(compiled.stderr);assert compiled.returncode==0
    observations=[]
    for name,policy,expired,stall in [('normal','progress',False,False),('expired','progress',True,False),('progress-stall','progress',False,True),('interrupt-stall','interrupt',False,True),('combined-stall','both',False,True)]:
        with tempfile.TemporaryDirectory(prefix='hara-storage-') as temp:
            folder=pathlib.Path(temp);path=folder/'probe.db'
            fixture=sqlite3.connect(path);fixture.execute('PRAGMA journal_mode=WAL');fixture.execute('CREATE TABLE effects(value TEXT)');fixture.commit()
            # Keep fixture connection open to retain WAL; it performs no further writes.
            env=os.environ.copy()
            if stall:env.update(LD_PRELOAD=str(library),B013_WAL_PATH=str(path)+'-wal',B013_WAL_ARM=str(folder/'arm'),B013_NATIVE_TRACE=str(folder/'native.jsonl'))
            proc=subprocess.run([sys.executable,str(ROOT/'probe.py'),'writer',temp,policy,'expired' if expired else 'active'],env=env,timeout=10,capture_output=True,text=True)
            record=json.loads((folder/'writer.json').read_text());assert proc.returncode==-signal.SIGKILL
            read=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);rows=read.execute('SELECT value FROM effects').fetchall();read.close()
            native=[json.loads(line) for line in (folder/'native.jsonl').read_text().splitlines()] if stall else []
            record.update(case=name,policy=policy,writerExit=proc.returncode,rowsAfterCrash=rows,native=native,stderr=proc.stderr)
            (out/(name+'.json')).write_text(json.dumps(record,indent=2)+'\n');observations.append(record)
            fixture.close()
    assert len(observations[0]['rowsAfterCrash'])==1
    assert len(observations[1]['rowsAfterCrash'])==0
    for r in observations[2:]:
        assert len(r['native'])==1 and r['native'][0]['endMs']>r['expiry']
    summary={'kind':'STORAGE_CANCELLATION_RESEARCH','python':sys.version,'sqlite':sqlite3.sqlite_version,'cases':[{'case':r['case'],'lateDurableEffectObserved':bool(r['native'] and r['native'][0]['endMs']>r['expiry'] and r['rowsAfterCrash']),'effectRows':len(r['rowsAfterCrash']),'apiError':r['error']} for r in observations],'sources':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['probe.py','wal-stall.c']},'scope':'One synthetic row, actual WAL stall and SIGKILL; no Hannie adapter, provider, grant or full D-013 acceptance','acceptance':'HOLD'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
