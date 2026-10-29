"""Final local Prefect flow; task results are small artifact descriptors only."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault('PREFECT_HOME', str(Path(__file__).parent/'.prefect'))
os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED', 'false')
from prefect import flow, task, get_run_logger
from prefect.cache_policies import NO_CACHE
from prefect.context import get_run_context
from prefect.serializers import JSONSerializer
import lab
from publication import record_release
from release import cache_key, canonical, digest, file_digest


def preparation_cache(context, parameters):
    # The content key is path independent. Namespace persisted URI results by workspace.
    return digest(canonical({'workspace': parameters['root'], 'content_key': parameters['key']}))


@task(name='prepare-input', cache_key_fn=preparation_cache, persist_result=True,
      result_serializer=JSONSerializer(), retries=0)
def prepare_input(root: str, key: str, manifest_name: str):
    path = Path(root)
    config=lab.preparation_config(path,manifest_name)
    if cache_key(path/'input.txt', config) != key:
        raise ValueError('Input changed while preparing')
    return lab.prepare(path,config)


@task(name='obtain-existing-training-artifact', cache_policy=NO_CACHE, retries=0)
def obtain_artifact(root: str, manifest_name: str):
    manifest = lab.obtain(Path(root), manifest_name)
    return {'manifest_uri': manifest_name, 'model_id': manifest['model_id'],
            'model_sha256': manifest['model_sha256'], 'training': 'reuse; no retraining'}


@task(name='evaluate-release-admission', cache_policy=NO_CACHE, retries=0)
def admission(root: str, artifact: dict, report_name: str, prepared: dict):
    path = Path(root)
    manifest = lab.read(path/artifact['manifest_uri'])
    report = lab.assess(path, manifest, report_name, prepared)
    return {'report_uri': report_name, 'evaluation_run_id': report['evaluation_run_id'],
            'report_sha256': digest(canonical(report))}


@task(name='publish-accepted-pointer', cache_policy=NO_CACHE, retries=0)
def publication(root: str, artifact: dict, decision: dict, prepared: dict, fail_after_pointer: bool):
    path = Path(root)
    # Recheck the artifact and the decision at the publication boundary.
    manifest = lab.obtain(path, artifact['manifest_uri'])
    report = lab.assess(path, manifest, decision['report_uri'], prepared)
    if digest(canonical(report)) != decision['report_sha256']:
        raise ValueError('Decision changed during flow')
    return record_release(path, manifest, report, prepared, fail_after_pointer)


@flow(name='model-release', persist_result=False, log_prints=True, retries=0)
def release_flow(root: str, manifest_name='manifest-B.json', report_name='report-B.json',
                 fail_after_prepare=False, fail_after_pointer=False):
    path = Path(root).resolve()
    root = str(path)
    run_id = str(get_run_context().flow_run.id)
    lab.attempt(path, {'attempt_id': run_id, 'engine': 'prefect', 'status': 'started'})
    try:
        key = cache_key(path/'input.txt', lab.preparation_config(path,manifest_name))
        prepared_state = prepare_input(root, key, manifest_name, return_state=True)
        prepared = prepared_state.result()
        get_run_logger().info('PREPARATION_STATE=%s CONTENT_KEY=%s', prepared_state.name, key)
        if prepared['input_sha256'] != file_digest(path/'input.txt'):
            raise ValueError('Cached preparation does not match input')
        lab.attempt(path, {'attempt_id': run_id, 'stage': 'prepare', 'state': prepared_state.name, 'cache_key': key})
        if fail_after_prepare:
            raise RuntimeError('Injected failure after preparation')
        artifact = obtain_artifact(root, manifest_name)
        decision = admission(root, artifact, report_name, prepared)
        result = publication(root, artifact, decision, prepared, fail_after_pointer)
    except Exception as exc:
        lab.attempt(path, {'attempt_id': run_id, 'status': 'failed', 'error': str(exc)})
        raise
    lab.attempt(path, {'attempt_id': run_id, 'status': 'completed', **result})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, default=Path('.lab'))
    p.add_argument('--manifest', default='manifest-B.json')
    p.add_argument('--report', default='report-B.json')
    p.add_argument('--fail-after-prepare', action='store_true')
    p.add_argument('--fail-after-pointer', action='store_true')
    args = p.parse_args()
    release_flow(str(args.workspace.resolve()), args.manifest, args.report,
                 args.fail_after_prepare, args.fail_after_pointer)


if __name__ == '__main__':
    main()
