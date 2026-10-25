import hashlib
from pathlib import Path

from mlflow import MlflowClient

from evaluation.cli import current_reports
from evaluation.contract import read_json, write_json
from src.common import connect, digest, load_params, provenance
from scripts.package_submission import REPORT_DOCUMENTS, REPORT_METRICS, REPORT_LOGS


def main():
    _, candidate = current_reports()
    params = load_params()
    connect(params)
    client = MlflowClient()
    spec = candidate['model']
    registry = client.get_registered_model(spec['name'])
    sweep = read_json('metrics/sweep.json')
    parent = client.get_run(sweep['parent_id'])
    tracking = params['tracking']['uri'].rstrip('/')
    runs = {row['name']: row['run_id'] for row in sweep['rows']}
    runs['sweep'] = parent.info.run_id
    runs['evaluation'] = candidate['evaluation_run_id']
    runs['storage'] = read_json('metrics/storage-check.json')['run_id']
    links = {name: f'{tracking}/#/experiments/{client.get_run(run_id).info.experiment_id}/runs/{run_id}'
             for name, run_id in runs.items()}
    tests = hashlib.sha256()
    for path in sorted(Path('tests').glob('*')):
        if path.is_file():
            tests.update(path.name.encode())
            tests.update(path.read_bytes())
    evidence = dict(runs=runs, links=links, model=spec, aliases=registry.aliases,
                    protocol_sha256=candidate['protocol_sha256'],
                    golden_sha256=candidate['golden_sha256'],
                    tests_sha256=tests.hexdigest(), uv_lock_sha256=digest('uv.lock'),
                    provenance=provenance(params), quality_gate=read_json('metrics/quality-gate.json'))
    write_json('metrics/evidence.json', evidence)
    client.set_model_version_tag(spec['name'], spec['version'], 'evaluation_run_id', candidate['evaluation_run_id'])
    client.set_model_version_tag(spec['name'], spec['version'], 'quality_gate',
                                 'passed' if evidence['quality_gate']['passed'] else 'rejected')
    for directory, names in [('metrics', REPORT_METRICS + REPORT_LOGS), ('docs', REPORT_DOCUMENTS)]:
        for name in names:
            path = Path(directory) / name
            if path.is_file():
                client.log_artifact(candidate['evaluation_run_id'], str(path), f'evidence/{directory}')
    for path in sorted(Path('evaluation').glob('*.py')):
        client.log_artifact(candidate['evaluation_run_id'], str(path), 'evidence/evaluation')
    print('Ссылки, хеши, состояние реестра и доказательства сохранены: metrics/evidence.json')


if __name__ == '__main__':
    main()
