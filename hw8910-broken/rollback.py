"""Restore only a previously accepted release, with freshly verified files/gate."""
import argparse
from pathlib import Path
import lab
from publication import read, record_release, recover, release_identity
from artifacts import verify_artifact


def rollback(root, release_id):
    state = recover(root)
    if release_id not in {e['release_id'] for e in state['events']}:
        raise ValueError('Rollback target has never been accepted')
    saved = read(root/'releases'/f'{release_id}.json')
    manifest, report = saved['manifest'], saved['report']
    if release_identity(manifest,report)!=release_id:
        raise ValueError('Accepted release history changed')
    verify_artifact(manifest, root)
    if manifest.get('backend') == 'transformers':
        from gate import verify_decision
        verify_decision(manifest, report, root)
    result = record_release(root, manifest, report, action='rollback')
    lab.attempt(root, {'status': 'rollback', **result})
    print('ROLLBACK', manifest['model_id'])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--release-id', required=True)
    a = p.parse_args()
    rollback(a.workspace.resolve(), a.release_id)
