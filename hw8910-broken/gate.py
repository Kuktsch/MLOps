"""Recompute HW6–7 scores and its unchanged quality_gate from hashed raw evidence."""
import json
from pathlib import Path

from artifacts import local_path
from release import canonical, digest, file_digest, validate_release
from vendor.hw67_gate import score, quality_gate
from vendor.hw67_contract import validate_golden


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_bundle(root, sources):
    paths = {}
    for name, ref in sources.items():
        path = local_path(root, ref['uri'])
        if file_digest(path) != ref['sha256']:
            raise ValueError(f'Evaluation source changed: {name}')
        paths[name] = path
    required = {'baseline_eval', 'candidate_eval', 'baseline_outputs', 'candidate_outputs',
                'protocol', 'golden', 'behavioral', 'training_index', 'baseline_spec', 'training_import'}
    if not required <= paths.keys():
        raise ValueError('Missing full evaluation evidence')
    golden, behavioral, training = [rows(paths[n]) for n in ('golden', 'behavioral', 'training_index')]
    proof = validate_golden(golden, training, behavioral)
    protocol = read(paths['protocol'])
    for name, expected in protocol['code_hashes'].items():
        if file_digest(Path(__file__).parent/name) != expected:
            raise ValueError(f'Evaluation code changed: {name}')
    if protocol['golden_sha256'] != digest(canonical(golden)):
        raise ValueError('Golden set does not match protocol')
    if protocol['behavioral_sha256'] != digest(canonical(behavioral)):
        raise ValueError('Behavioral set does not match protocol')
    if protocol['training_index_sha256'] != digest(canonical(training)):
        raise ValueError('Training index does not match protocol')
    baseline_spec = read(paths['baseline_spec'])
    if baseline_spec != protocol['baseline_spec']:
        raise ValueError('Frozen baseline changed')
    baseline_hash = digest(canonical(baseline_spec))
    reports = {}
    for role in ('baseline', 'candidate'):
        report, outputs = read(paths[role+'_eval']), read(paths[role+'_outputs'])
        if report.get('status') != 'complete' or not isinstance(report.get('evaluation_run_id'),str) or not report['evaluation_run_id']:
            raise ValueError('Incomplete source evaluation')
        by_id = {o['id']: o for o in outputs}
        if len(by_id) != len(outputs) or set(by_id) != {r['id'] for r in golden+behavioral}:
            raise ValueError('Raw output IDs do not match the complete evaluation set')
        calculated = score(golden, [by_id[r['id']] for r in golden])
        if any(report[k] != calculated[k] for k in ('overall', 'slices', 'per_item')):
            raise ValueError('Scores do not match raw model answers')
        if report['behavioral'] != score(behavioral, [by_id[r['id']] for r in behavioral]):
            raise ValueError('Behavioral scores do not match raw answers')
        if (report['protocol_sha256'] != digest(canonical(protocol)) or
                report['golden_sha256'] != protocol['golden_sha256'] or
                report['baseline_spec_sha256'] != baseline_hash or
                report['outputs_sha256'] != digest(canonical(outputs)) or report['leakage'] != proof):
            raise ValueError('Stale report/protocol/output/leakage binding')
        binding = protocol['models'][role]
        for key in ('model_id', 'model_sha256', 'runtime_sha256'):
            if report[key] != binding[key]:
                raise ValueError(f'Evaluation model binding changed: {key}')
        reports[role] = report
    imported = read(paths['training_import'])
    if imported['run_status'] != 'FINISHED' or reports['candidate']['model'] != imported['candidate_spec']:
        raise ValueError('Training run not complete or different candidate')
    if reports['baseline']['model'] != baseline_spec:
        raise ValueError('Different baseline evaluated')
    return reports, protocol, imported


def derive_report(manifest, root, sources):
    reports, protocol, imported = load_bundle(root, sources)
    gate_result, reason = None, None
    try:
        gate_result = quality_gate(reports['baseline'], reports['candidate'], protocol['config']['critical_slices'])
        if gate_result.get('passed') is not True:
            raise ValueError('Gate did not return boolean PASS')
    except ValueError as exc:
        reason = str(exc)
    role = manifest['evaluation_role']
    evaluated = reports[role]
    for key in ('model_id', 'model_sha256', 'runtime_sha256', 'protocol_sha256', 'golden_sha256'):
        if manifest[key] != evaluated[key]:
            raise ValueError(f'Manifest not evaluated with this runtime/artifact: {key}')
    if manifest['evaluation_model'] != evaluated['model']:
        raise ValueError('Manifest points at a different evaluated model')
    retained = (role == 'baseline' and evaluated['model'] == protocol['baseline_spec'] and
                evaluated['model']['revision'] == manifest['runtime']['base_revision'] and
                evaluated['overall']['errors'] == 0)
    passed = retained or gate_result is not None
    report = {k: manifest[k] for k in ('model_id', 'model_sha256', 'runtime_sha256', 'protocol_sha256', 'golden_sha256')}
    report.update(status='complete', passed=passed, evaluation_run_id=evaluated['evaluation_run_id'],
                  metrics={k: evaluated['overall'][k] for k in ('accuracy', 'format_rate')},
                  admission_kind='retain-frozen-baseline' if retained else 'hw67-quality-gate',
                  candidate_gate={'passed': gate_result is not None, 'reason': reason, 'result': gate_result},
                  sources=sources, training_run_id=imported['candidate_spec']['run_id'], synthetic=False)
    return report


def verify_decision(manifest, report, root):
    if report.get('synthetic') is not False:
        raise ValueError('A fixture is not a real model admission')
    expected = derive_report(manifest, root, report['sources'])
    if expected != report:
        raise ValueError('Release report differs from recomputed gate decision')
    return report['passed']


def verify_accepted(root, manifest):
    from publication import release_identity
    state = read(Path(root)/'release-state.json')
    for event in state['events']:
        saved = read(Path(root)/'releases'/(event['release_id']+'.json'))
        if saved['manifest'] == manifest:
            if release_identity(manifest,saved['report'])!=event['release_id']:
                raise ValueError('Accepted release history changed')
            verify_decision(manifest, saved['report'], root)
            validate_release(manifest, saved['report'])
            return
    raise ValueError('Pointer is not a previously accepted release')
