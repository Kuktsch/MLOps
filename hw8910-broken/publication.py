"""Single-writer durable intent + atomic pointer + recoverable event projection.

release-state.json is the authoritative event ledger; publications.jsonl is a
rebuildable projection. A pending intent bridges the two atomic replacements.
"""
import json
import os
from pathlib import Path
from release import atomic_bytes, atomic_json, canonical, digest, manifest_bytes, publish, validate_release


def read(path):
    return json.loads(Path(path).read_text())


def release_identity(manifest,report):
    return digest(canonical({'manifest':manifest,'decision':report}))


def project(root, state):
    atomic_bytes(root / 'publications.jsonl', b''.join(canonical(e) + b'\n' for e in state['events']))


def recover(root):
    root = Path(root)
    path = root / 'release-state.json'
    state = read(path) if path.exists() else {'events': [], 'pending': None}
    pending = state['pending']
    if pending:
        accepted = root / 'accepted.json'
        if accepted.exists() and digest(accepted.read_bytes()) == pending['pointer_sha256']:
            if pending['event']['release_id'] not in {e['release_id'] for e in state['events']}:
                state['events'].append(pending['event'])
            print('RECOVERED_PUBLICATION', pending['event']['release_id'], flush=True)
        state['pending'] = None
        atomic_json(path, state)
    project(root, state)
    return state


def record_release(root, manifest, report, prepared=None, fail_after_pointer=False, action='release'):
    root = Path(root)
    validate_release(manifest, report)
    state = recover(root)
    release_id = release_identity(manifest,report)
    event = {'release_id': release_id, 'model_id': manifest['model_id'],
             'runtime_sha256': manifest['runtime_sha256'], 'report_sha256': digest(canonical(report)),
             'evaluation_run_id': report['evaluation_run_id'], 'action': action,
             'prepared': prepared and prepared['input_sha256']}
    history = root / 'releases'
    history.mkdir(exist_ok=True)
    atomic_json(history / (release_id + '.json'), {'manifest': manifest, 'report': report})
    if release_id in {e['release_id'] for e in state['events']}:
        publish(manifest, report, root / 'accepted.json')
        print('ALREADY_PUBLISHED', release_id, flush=True)
        return {'release_id': release_id, 'new_event': False}
    state['pending'] = {'event': event, 'pointer_sha256': digest(manifest_bytes(manifest))}
    atomic_json(root / 'release-state.json', state)
    publish(manifest, report, root / 'accepted.json')
    if fail_after_pointer or os.environ.get('HW8910_FAIL_AFTER_POINTER') == '1':
        raise RuntimeError('Injected crash after pointer, before event')
    state['events'].append(event)
    state['pending'] = None
    atomic_json(root / 'release-state.json', state)
    project(root, state)
    print('PUBLISHED', manifest['model_id'], release_id, flush=True)
    return {'release_id': release_id, 'new_event': True}
