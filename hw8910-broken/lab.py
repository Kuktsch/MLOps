"""Исполняемый прототип для расследования. Только синтетические данные, без модели.

Запускайте в отдельном каталоге .lab. Этот последовательный прототип надо
превратить в корректный Prefect-flow; его зелёный статус не доказывает корректность.
"""
import argparse
import hashlib
import json
from pathlib import Path
import release
import os
import uuid
from artifacts import verify_artifact
from publication import record_release


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path,value):
    release.atomic_json(path,value)


def initialize(root):
    if root.exists():
        raise FileExistsError('Рабочий каталог уже существует. Выберите новый --workspace.')
    root.mkdir(parents=True)
    runtime={'base_revision':'fixture-only','tokenizer_sha256':'a'*64,
             'template_sha256':'b'*64,'generation':{'max_new_tokens':32,'do_sample':False},'dtype':'float32'}
    for version in ['A','B']:
        artifact=root/f'model-{version}.txt';artifact.write_text(f'STUB ONLY — version {version}\n')
        files={artifact.name:digest(artifact.read_bytes())}
        m={'schema_version':1,'model_id':f'fixture-{version}',
           'artifact_uri':artifact.name,'model_sha256':digest(canonical(files)),
           'protocol_sha256':'d'*64,'golden_sha256':'e'*64,
           'runtime_sha256':digest(canonical(runtime)),'runtime':runtime,'file_hashes':files}
        report={k:m[k] for k in ['model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256']}
        report.update(status='complete',passed=True,evaluation_run_id=f'fixture-eval-{version}',metrics={'accuracy':.8,'format_rate':1.0},synthetic=True)
        write(root/f'manifest-{version}.json',m);write(root/f'report-{version}.json',report)
    write(root/'accepted.json',read(root/'manifest-A.json'))
    report=read(root/'report-B.json');report['status']='running';report['passed']='false'
    write(root/'report-incomplete.json',report)
    report=read(root/'report-B.json');report['passed']=False
    write(root/'report-reject.json',report)
    write(root/'config.json',{'tokenizer_revision':'r1','template_sha256':'b'*64,'max_length':128,'code_revision':'prepare-v1'})
    (root/'input.txt').write_text('Первый пример\nВторой пример\n')
    record_release(root,read(root/'manifest-A.json'),read(root/'report-A.json'),action='bootstrap-stub')
    print('Создан синтетический стенд:',root)


def preparation_config(root,manifest_name=None):
    config={**read(root/'config.json'),'processor_sha256':release.file_digest(Path(__file__))}
    if manifest_name:
        manifest=read(root/manifest_name)
        if manifest.get('backend')=='transformers':
            runtime=manifest['runtime']
            config.update(tokenizer_revision=runtime['tokenizer_sha256'],template_sha256=runtime['template_sha256'],
                          max_length=runtime['max_input_tokens'])
    return config


def prepare(root,config=None):
    config=config or preparation_config(root);key=release.cache_key(root/'input.txt',config)
    cache=root/'cache';cache.mkdir(exist_ok=True);entry=cache/(key+'.json')
    if entry.exists():
        result=read(entry);print('CACHE_HIT',result['input_sha256']);return result
    payload=(root/'input.txt').read_bytes()
    lines=[line for line in payload.decode('utf-8').splitlines() if line.strip()]
    if not lines:raise ValueError('Empty input')
    if config.get('kind')=='golden-jsonl':
        rows=[json.loads(line) for line in lines]
        if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate input ids')
        for row in rows:
            if not isinstance(row.get('input'),str) or not row['input'].strip() or row.get('expected') not in row.get('choices',[]):
                raise ValueError('Invalid golden input schema')
    result={'input_sha256':digest(payload),'rows':len(lines),'config':config,'cache_key':key,
            'result_uri':str(entry.resolve())}
    write(entry,result);print('PREPARED',result['input_sha256']);return result


def obtain(root,manifest_name):
    manifest=read(root/manifest_name)
    verify_artifact(manifest,root)
    print('ARTIFACT_VERIFIED',manifest['model_id'],'existing run; no training',flush=True)
    return manifest


def assess(root,manifest,report_name,prepared=None):
    report=read(root/report_name)
    if manifest.get('backend')=='transformers':
        from gate import verify_decision
        verify_decision(manifest,report,root)
        if prepared is not None and prepared['input_sha256']!=report['sources']['golden']['sha256']:
            raise ValueError('Prepared input differs from evaluated golden: a new evaluation is required')
    release.validate_release(manifest,report)
    return report


def attempt(root,record):
    with (root/'attempts.jsonl').open('a') as stream:
        stream.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
        stream.flush();os.fsync(stream.fileno())


def run(root,report_name,fail_after_prepare=False,manifest_name='manifest-B.json',fail_after_pointer=False):
    attempt_id=str(uuid.uuid4())
    attempt(root,{'attempt_id':attempt_id,'status':'started'})
    try:
        prepared=prepare(root,preparation_config(root,manifest_name))
        if fail_after_prepare:raise RuntimeError('Инъекция сбоя после подготовки')
        manifest=obtain(root,manifest_name);report=assess(root,manifest,report_name,prepared)
        result=record_release(root,manifest,report,prepared,fail_after_pointer)
    except Exception as exc:
        attempt(root,{'attempt_id':attempt_id,'status':'failed','error':str(exc)})
        raise
    attempt(root,{'attempt_id':attempt_id,'status':'completed',**result})
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,default=Path('.lab'))
    sub=parser.add_subparsers(dest='command',required=True);sub.add_parser('init')
    run_parser=sub.add_parser('run');run_parser.add_argument('--report',default='report-B.json');run_parser.add_argument('--fail-after-prepare',action='store_true')
    run_parser.add_argument('--manifest',default='manifest-B.json');run_parser.add_argument('--fail-after-pointer',action='store_true')
    args=parser.parse_args()
    if args.command=='init':initialize(args.workspace)
    else:run(args.workspace,args.report,args.fail_after_prepare,args.manifest,args.fail_after_pointer)


if __name__=='__main__':main()
