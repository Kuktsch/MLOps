"""End-to-end JSON latency, preserving every attempt including failures/timeouts."""
import argparse
import csv
import json
import statistics
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def request(base_url, row, concurrency, index, limit):
    record={'attempt_id':f'c{concurrency}-{index:02d}-{uuid.uuid4()}', 'mode':concurrency,
            'prompt_id':row['id'], 'max_new_tokens':limit, 'status':None,'error':None,
            'client_seconds':None,'generation_seconds':None,'queue_seconds':None,
            'model_id':None,'runtime_sha256':None,'output_tokens':None,'request_id':None}
    start=time.perf_counter()
    try:
        req=urllib.request.Request(base_url+'/generate',data=json.dumps({'prompt':row['input'],'max_new_tokens':limit}).encode(),
                                   headers={'Content-Type':'application/json'})
        try:
            response=urllib.request.urlopen(req,timeout=120)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            record['status']=response.status
            payload=json.loads(response.read())
        record['response']=payload
        if record['status']==200:
            for key in ['generation_seconds','queue_seconds','model_id','runtime_sha256','output_tokens','request_id']:
                record[key]=payload[key]
        else:
            record['error']=str(payload)
    except Exception as exc:
        record['error']=f'{type(exc).__name__}: {exc}'
    finally:
        record['client_seconds']=time.perf_counter()-start
    return record


def benchmark(base_url, prompts, output, limit=32):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    summaries=[]
    with (output/'attempts.jsonl').open('w') as raw:
        for concurrency in (1,2):
            start=time.perf_counter();records=[]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures=[pool.submit(request,base_url,row,concurrency,i,limit) for i,row in enumerate(prompts,1)]
                for future in as_completed(futures):
                    record=future.result();records.append(record)
                    raw.write(json.dumps(record,ensure_ascii=False)+'\n');raw.flush()
            elapsed=time.perf_counter()-start
            success=[r for r in records if r['status']==200 and r['error'] is None]
            failures=[r for r in records if r not in success]
            row={'concurrency':concurrency,'n':len(records),'successes':len(success),'errors':len(failures),
                 'batch_seconds':elapsed,'successful_requests_per_second':len(success)/elapsed,
                 'mean_success_client_seconds':statistics.mean(r['client_seconds'] for r in success) if success else None,
                 'max_success_client_seconds':max((r['client_seconds'] for r in success),default=None),
                 'mean_error_client_seconds':statistics.mean(r['client_seconds'] for r in failures) if failures else None,
                 'max_error_client_seconds':max((r['client_seconds'] for r in failures),default=None),
                 'mean_generation_seconds':statistics.mean(r['generation_seconds'] for r in success) if success else None,
                 'mean_queue_seconds':statistics.mean(r['queue_seconds'] for r in success) if success else None,
                 'actual_output_tokens':sum(r['output_tokens'] for r in success)}
            summaries.append(row)
            print('BENCHMARK',json.dumps(row,ensure_ascii=False),flush=True)
    (output/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n')
    with (output/'summary.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
    return summaries


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8091')
    p.add_argument('--prompts',type=Path,default=Path('evidence/model/golden.jsonl'))
    p.add_argument('--output',type=Path,default=Path('evidence/benchmark'));p.add_argument('--n',type=int,default=8)
    a=p.parse_args();rows=[json.loads(s) for s in a.prompts.read_text().splitlines() if s.strip()]
    benchmark(a.base_url,rows[:a.n],a.output)
