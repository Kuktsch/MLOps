"""Reuse the finished HW67 run and rerun full evaluation with the serving backend.

No training. We rerun 54 golden + 3 behavioral items for BOTH versions because
this project introduces explicit runtime and backend hashes.
"""
import argparse
import gc
import importlib.metadata
import json
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from release import atomic_json, canonical, digest, file_digest
from artifacts import verify_artifact
from model_backend import TransformersBackend
from vendor.hw67_gate import score
from vendor.hw67_contract import validate_golden
from gate import derive_report, verify_decision
from publication import record_release


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def hashes(root, names):
    return {name: file_digest(root/name) for name in sorted(names)}


def main():
    import mlflow
    import torch
    import yaml
    from mlflow import MlflowClient
    from transformers import AutoTokenizer
    p = argparse.ArgumentParser()
    p.add_argument('--hw67', type=Path, default=PROJECT.parent/'mlops26-hw6-7/hw67-broken')
    p.add_argument('--workspace', type=Path, default=PROJECT/'.real')
    p.add_argument('--evidence', type=Path, default=PROJECT/'evidence/model')
    p.add_argument('--tracking-uri', default='http://127.0.0.1:5006')
    p.add_argument('--device', choices=['cuda', 'cpu'], default='cuda')
    args = p.parse_args()
    old, root = args.hw67.resolve(), args.workspace.resolve()
    out = args.evidence.resolve()
    if root.exists():
        raise FileExistsError('Choose a fresh workspace; existing evidence must not be overwritten')
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Choose a fresh --evidence directory; accepted evaluation sources are immutable')
    root.mkdir(parents=True)
    out.mkdir(parents=True,exist_ok=True)
    original = out/'hw67-original'
    original.mkdir(exist_ok=True)
    for name in ['evaluation/params.json', 'evaluation/baseline.json', 'metrics/candidate-model.json',
                 'metrics/baseline-eval.json', 'metrics/candidate-eval.json', 'metrics/baseline-outputs.json',
                 'metrics/candidate-outputs.json', 'metrics/quality-gate.json', 'metrics/pre-evaluation.json']:
        shutil.copyfile(old/name, original/Path(name).name)
    for name in ['golden', 'behavioral', 'training-index']:
        shutil.copyfile(old/'data/eval'/f'{name}.jsonl', out/f'{name}.jsonl')
    config = read(old/'evaluation/params.json')
    spec = read(old/'metrics/candidate-model.json')
    baseline = read(old/'evaluation/baseline.json')
    atomic_json(out/'baseline-spec.json', baseline)
    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient()
    run = client.get_run(spec['run_id'])
    if run.info.status != 'FINISHED':
        raise ValueError('Training run is not FINISHED')
    version = client.get_model_version(spec['name'], spec['version'])
    if version.run_id != spec['run_id']:
        raise ValueError('Registry version does not match run')
    model_root = PROJECT/'.artifacts/model'
    if not model_root.exists():
        (PROJECT/'.artifacts').mkdir(exist_ok=True)
        client.download_artifacts(spec['run_id'], 'model', str(PROJECT/'.artifacts'))
    mlmodel = yaml.safe_load((model_root/'MLmodel').read_text())
    if mlmodel['run_id'] != spec['run_id']:
        raise ValueError('Downloaded artifact belongs to another training run')
    adapter = (model_root/mlmodel['flavors']['python_function']['artifacts']['adapter']['path']).resolve()
    if not adapter.is_relative_to(model_root):
        raise ValueError('Invalid adapter location')
    training = read(adapter/'manifest.json')
    if training['model']['name'] != baseline['name'] or training['model']['revision'] != baseline['revision']:
        raise ValueError('Training and frozen baseline have different bases')
    atomic_json(out/'training-import.json', {'candidate_spec': spec, 'run_status': run.info.status,
        'training_run_id': spec['run_id'], 'training_run_uri': f'runs:/{spec["run_id"]}/model',
        'tracking_uri': args.tracking_uri, 'reused_existing_training_run': True, 'training_executed': False,
        'training_manifest': training, 'mlmodel_sha256': file_digest(model_root/'MLmodel'),
        'original_evaluation_run_id': read(old/'metrics/baseline-eval.json')['evaluation_run_id']})
    base = Path.home()/'.cache/huggingface/hub'/('models--'+baseline['name'].replace('/', '--'))/'snapshots'/baseline['revision']
    if not base.exists():
        from huggingface_hub import snapshot_download
        base = Path(snapshot_download(baseline['name'], revision=baseline['revision']))
    base_files = hashes(base, [f.name for f in base.iterdir() if f.is_file()])
    manifests = {}
    libraries = {name: importlib.metadata.version(name) for name in
                 ['torch', 'transformers', 'peft', 'tokenizers', 'safetensors', 'accelerate', 'huggingface-hub', 'numpy']}
    for role, artifact, model in [('baseline', base, baseline), ('candidate', adapter, spec)]:
        tok_root = base if role == 'baseline' else adapter
        tok_names = [f.name for f in tok_root.iterdir() if f.is_file() and
                     (f.name.startswith('tokenizer') or f.name in ['chat_template.jinja', 'vocab.json', 'merges.txt', 'special_tokens_map.json'])]
        tokenizer_files = hashes(tok_root, tok_names)
        tokenizer = AutoTokenizer.from_pretrained(tok_root, local_files_only=True)
        runtime = {'base_name': baseline['name'], 'base_revision': baseline['revision'],
            'base_uri': str(base), 'base_files': base_files, 'base_files_sha256': digest(canonical(base_files)),
            'tokenizer_uri': str(tok_root), 'tokenizer_files': tokenizer_files,
            'tokenizer_sha256': digest(canonical(tokenizer_files)),
            'template_sha256': digest(tokenizer.chat_template.encode()),
            'generation': {k: config[k] for k in ['system', 'max_new_tokens', 'enable_thinking', 'seed']},
            'dtype': training['model']['dtype'], 'device': args.device, 'max_input_tokens': 1024,
            'libraries': libraries, 'backend_code_sha256': file_digest(PROJECT/'model_backend.py')}
        runtime['generation']['do_sample'] = False
        files = base_files if role == 'baseline' else hashes(adapter, [f.name for f in adapter.iterdir() if f.is_file()])
        manifest = {'schema_version': 1, 'model_id': 'baseline-qwen3-'+baseline['revision'] if role=='baseline' else 'adapter-'+spec['run_id'],
            'artifact_uri': str(artifact), 'model_sha256': digest(canonical(files)), 'file_hashes': files,
            'runtime': runtime, 'runtime_sha256': digest(canonical(runtime)), 'backend': 'transformers',
            'model_kind': 'base' if role=='baseline' else 'adapter', 'evaluation_role': role, 'evaluation_model': model,
            'protocol_sha256': '0'*64, 'golden_sha256': '0'*64}
        manifests[role] = manifest
    golden, behavioral, training_rows = [rows(out/(name+'.jsonl')) for name in ['golden', 'behavioral', 'training-index']]
    leakage = validate_golden(golden, training_rows, behavioral)
    protocol = {'config': config, 'baseline_spec': baseline,
        'golden_sha256': digest(canonical(golden)), 'behavioral_sha256': digest(canonical(behavioral)),
        'training_index_sha256': digest(canonical(training_rows)),
        'code_hashes': {name: file_digest(PROJECT/name) for name in ['model_backend.py', 'vendor/hw67_gate.py', 'vendor/hw67_contract.py']},
        'models': {role: {k: m[k] for k in ['model_id', 'model_sha256', 'runtime_sha256']} for role, m in manifests.items()},
        'generation_limit_policy': 'fixed: request must equal evaluated max_new_tokens',
        'note': 'Full reevaluation for the explicitly hashed serving runtime; no training'}
    atomic_json(out/'protocol.json', protocol)
    for role, manifest in manifests.items():
        manifest.update(protocol_sha256=digest(canonical(protocol)), golden_sha256=protocol['golden_sha256'])
        atomic_json(root/f'manifest-{role}.json', manifest)
        atomic_json(out/f'manifest-{role}.json', manifest)
    shutil.copyfile(out/'golden.jsonl', root/'input.txt')
    atomic_json(root/'config.json', {'kind': 'golden-jsonl', 'tokenizer_revision': manifests['candidate']['runtime']['tokenizer_sha256'],
        'template_sha256': manifests['candidate']['runtime']['template_sha256'], 'max_length': 1024,
        'code_revision': file_digest(PROJECT/'lab.py')})
    mlflow.set_experiment('hw8910-evaluation')
    with mlflow.start_run(run_name='same-backend-baseline-candidate-no-training') as evaluation:
        eval_id = evaluation.info.run_id
        for role, manifest in manifests.items():
            print('LOAD_REAL', role, manifest['model_id'], flush=True)
            verify_artifact(manifest, root)
            backend = TransformersBackend(manifest, root)
            backend.warmup()
            outputs = []
            for index, row in enumerate(golden+behavioral):
                start = time.perf_counter()
                raw, error, tokens = '', None, 0
                try:
                    result = backend.generate(row['input'], config['max_new_tokens'])
                    raw, tokens = result['answer'], result['output_tokens']
                except Exception as exc:
                    error = f'{type(exc).__name__}: {exc}'
                outputs.append({'id': row['id'], 'raw': raw, 'error': error,
                                'latency_seconds': time.perf_counter()-start, 'output_tokens': tokens})
                if (index+1)%10 == 0:
                    print('EVALUATED', role, index+1, 'of', len(golden+behavioral), flush=True)
            atomic_json(out/f'{role}-outputs.json', outputs)
            by_id = {r['id']: r for r in outputs}
            report = score(golden, [by_id[r['id']] for r in golden])
            report.update(status='complete', model=manifest['evaluation_model'],
                evaluation_run_id=eval_id, protocol_sha256=manifest['protocol_sha256'],
                golden_sha256=manifest['golden_sha256'], baseline_spec_sha256=digest(canonical(baseline)),
                behavioral=score(behavioral, [by_id[r['id']] for r in behavioral]), leakage=leakage,
                outputs_sha256=digest(canonical(outputs)), **{k: manifest[k] for k in ['model_id','model_sha256','runtime_sha256']})
            atomic_json(out/f'{role}-eval.json', report)
            mlflow.log_metrics({f'{role}.{k}': report['overall'][k] for k in ['accuracy', 'format_rate']})
            print('METRICS', role, report['overall'], flush=True)
            del backend
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        names = {'baseline_eval': 'baseline-eval.json', 'candidate_eval': 'candidate-eval.json',
                 'baseline_outputs': 'baseline-outputs.json', 'candidate_outputs': 'candidate-outputs.json',
                 'protocol': 'protocol.json', 'golden': 'golden.jsonl', 'behavioral': 'behavioral.jsonl',
                 'training_index': 'training-index.jsonl', 'baseline_spec': 'baseline-spec.json', 'training_import': 'training-import.json'}
        sources = {name: {'uri': os.path.relpath(out/filename, root), 'sha256': file_digest(out/filename)} for name, filename in names.items()}
        for role, manifest in manifests.items():
            report = derive_report(manifest, root, sources)
            filename = 'release-report.json' if role=='candidate' else 'release-report-baseline.json'
            atomic_json(root/filename, report)
            atomic_json(out/filename, report)
            print('ADMISSION', role, report['passed'], report['candidate_gate']['reason'], flush=True)
        baseline_report = read(root/'release-report-baseline.json')
        verify_artifact(manifests['baseline'],root)
        verify_decision(manifests['baseline'],baseline_report,root)
        record_release(root, manifests['baseline'], baseline_report, action='retain-frozen-baseline')
        shutil.copyfile(root/'accepted.json', out/'accepted.json')
        atomic_json(out/'evaluation-run.json', {'evaluation_run_id': eval_id, 'training_run_id': spec['run_id'],
            'uri': args.tracking_uri, 'n_golden': len(golden), 'n_behavioral': len(behavioral),
            'device': args.device, 'libraries': libraries, 'candidate_admitted': read(root/'release-report.json')['passed']})
        mlflow.set_tags({'kind': 'evaluation', 'training_run_id': spec['run_id'], 'no_training': 'true',
                         'protocol_sha256': digest(canonical(protocol))})
        for file in out.glob('*.json'):
            mlflow.log_artifact(str(file), 'evaluation')
    print('REAL_WORKSPACE_READY', root, flush=True)


if __name__ == '__main__':
    main()
