"""Real GPU smoke, invalid-request proof, benchmark, and actual API restart."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
sys.path.insert(0,str(Path(__file__).parent))
from release import atomic_json
from benchmark import benchmark


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output-root',type=Path,default=PROJECT/'evidence/synced-api')
    p.add_argument('--workspace',type=Path,default=PROJECT/'.real-synced')
    p.add_argument('--evaluation-evidence',type=Path,default=PROJECT/'evidence/model-synced')
    args=p.parse_args()
    workspace=args.workspace.resolve()
    evaluation_evidence=args.evaluation_evidence.resolve()
    accepted=json.loads((workspace/'accepted.json').read_text())
    limit=accepted['runtime']['generation']['max_new_tokens']
    output=args.output_root.resolve()
    evidence=output/'api';evidence.mkdir(parents=True,exist_ok=True)
    logs=output/'logs';logs.mkdir(parents=True,exist_ok=True)
    records=[]
    def call(port,path,payload=None,timeout=4):
        req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',
            data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
        start=time.perf_counter()
        try:
            response=urllib.request.urlopen(req,timeout=timeout)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:status,body=response.status,json.loads(response.read())
        records.append({'path':path,'payload':payload,'status':status,'body':body,'client_seconds':time.perf_counter()-start})
        return status,body
    @contextmanager
    def server(label):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with (logs/f'real-api-{label}.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,str(PROJECT/'service.py'),'--workspace',str(workspace),
                '--port',str(port),'--backend','transformers','--debug','--warmup-seconds','1'],cwd=PROJECT,
                env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'},stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+150
                initial_ready=None
                while time.monotonic()<deadline:
                    if proc.poll() is not None:raise RuntimeError('API exited; inspect server log')
                    try:
                        if call(port,'/health')[0]==200:
                            initial_ready=call(port,'/ready')[0];break
                    except OSError:time.sleep(.1)
                assert initial_ready==503,initial_ready
                while time.monotonic()<deadline:
                    status,ready=call(port,'/ready')
                    if status==200:break
                    debug=call(port,'/debug')[1]
                    if debug['load_error']:raise RuntimeError(debug['load_error'])
                    time.sleep(.2)
                else:raise TimeoutError('Model did not become ready')
                print('REAL_READY',label,ready,flush=True)
                yield port
            finally:
                proc.terminate()
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
    golden=[json.loads(s) for s in (evaluation_evidence/'golden.jsonl').read_text().splitlines() if s.strip()]
    evaluated=json.loads((evaluation_evidence/(accepted['evaluation_role']+'-eval.json')).read_text())
    correct_id=next(r['id'] for r in evaluated['per_item'] if r['correct'])
    expected_raw=next(r['raw'] for r in evaluated['per_item'] if r['id']==correct_id)
    prompt=next(r for r in golden if r['id']==correct_id)['input']
    responses=[]
    with server('first') as port:
        before=call(port,'/debug')[1]['calls']
        invalid_status,_=call(port,'/generate',{'prompt':'test','max_new_tokens':100000})
        after=call(port,'/debug')[1]['calls']
        assert invalid_status==422 and before==after,(invalid_status,before,after)
        status,result=call(port,'/generate',{'prompt':prompt,'max_new_tokens':limit},timeout=120)
        assert status==200 and result['output_tokens']>0 and 'STUB ONLY' not in result['answer']
        assert result['answer']==expected_raw, (result['answer'],expected_raw)
        assert result['model_id']==accepted['model_id']
        assert result['runtime_sha256']==accepted['runtime_sha256']
        responses.append(result)
        atomic_json(evidence/'real-response.json',{'prompt_id':correct_id,'prompt':prompt,'response':result,
                                                 'invalid_status':invalid_status,
                                                 'calls_before_invalid':before,'calls_after_invalid':after})
        benchmark(f'http://127.0.0.1:{port}',golden[:8],output/'benchmark',limit=limit)
        debug=call(port,'/debug')[1]
        assert debug['calls']==17 and debug['warmup_calls']==1,debug
    with server('restart') as port:
        status,result=call(port,'/generate',{'prompt':prompt,'max_new_tokens':limit},timeout=120)
        assert status==200
        responses.append(result)
    assert responses[0]['model_id']==responses[1]['model_id']
    assert responses[0]['runtime_sha256']==responses[1]['runtime_sha256']
    assert responses[0]['answer']==responses[1]['answer']
    atomic_json(evidence/'restart.json',responses)
    with (evidence/'requests.jsonl').open('w') as f:
        for row in records:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print('REAL_API_VERIFIED',responses[0]['answer'],flush=True)


if __name__=='__main__':main()
