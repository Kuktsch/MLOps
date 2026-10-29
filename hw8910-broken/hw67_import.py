"""Validate the actual HW6–7 evaluation before using it in a serving release."""
import json
from pathlib import Path

from release import file_digest
from vendor.hw67_contract import fingerprint, validate_golden
from vendor.hw67_gate import quality_gate, score


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def validate_upstream(snapshot, data):
    snapshot, data = Path(snapshot), Path(data)
    project = Path(__file__).parent
    for source, vendored in [('solution.py', 'hw67_gate.py'), ('contract.py', 'hw67_contract.py')]:
        if file_digest(snapshot/'evaluation'/source) != file_digest(project/'vendor'/vendored):
            raise ValueError('HW6–7 scoring code differs from the serving gate')
    config, baseline, candidate = [read(snapshot/name) for name in
                                   ('params.json', 'baseline.json', 'candidate-model.json')]
    golden, behavioral, training = [rows(data/(name+'.jsonl')) for name in
                                    ('golden', 'behavioral', 'training-index')]
    leakage = validate_golden(golden, training, behavioral)
    protocol = fingerprint(dict(config=config, golden=golden, behavioral=behavioral,
        training_index=training, evaluation_code={p.name: p.read_text()
            for p in sorted((snapshot/'evaluation').glob('*.py'))}))
    reports = {}
    for role, spec in [('baseline', baseline), ('candidate', candidate)]:
        report, outputs = [read(snapshot/(role+suffix)) for suffix in ('-eval.json', '-outputs.json')]
        if report.get('status') != 'complete' or report.get('model') != spec:
            raise ValueError('Incomplete or different HW6–7 model')
        if (not report.get('evaluation_run_id') or report['protocol_sha256'] != protocol or
                report['golden_sha256'] != fingerprint(golden) or
                report['baseline_spec_sha256'] != fingerprint(baseline) or
                report['outputs_sha256'] != fingerprint(outputs) or report['leakage'] != leakage):
            raise ValueError('Stale HW6–7 evaluation: rerun make evaluate and make eval')
        by_id = {r['id']: r for r in outputs}
        if len(by_id) != len(outputs) or set(by_id) != {r['id'] for r in golden+behavioral}:
            raise ValueError('Incomplete HW6–7 raw output IDs')
        calculated = score(golden, [by_id[r['id']] for r in golden])
        if (any(report[k] != calculated[k] for k in ('overall', 'slices', 'per_item')) or
                report['behavioral'] != score(behavioral, [by_id[r['id']] for r in behavioral])):
            raise ValueError('HW6–7 scores do not match raw answers')
        reports[role] = report
    if reports['baseline']['evaluation_run_id'] != reports['candidate']['evaluation_run_id']:
        raise ValueError('HW6–7 reports belong to different evaluation runs')
    try:
        decision = quality_gate(reports['baseline'], reports['candidate'], config['critical_slices'])
    except ValueError as exc:
        decision = dict(passed=False, reason=str(exc))
    if read(snapshot/'quality-gate.json') != decision:
        raise ValueError('Stale HW6–7 gate: rerun make eval')
    return dict(evaluation_run_id=reports['baseline']['evaluation_run_id'],
        training_run_id=candidate['run_id'], protocol_sha256=protocol,
        config=config, decision=decision,
        scores={role: report['overall'] for role, report in reports.items()},
        snapshot_files={str(p.relative_to(snapshot)): file_digest(p)
            for p in sorted(snapshot.rglob('*')) if p.is_file()})


def verify_answers(snapshot, role, outputs):
    expected = read(Path(snapshot)/(role+'-outputs.json'))
    normalize = lambda values: {r['id']: (r['raw'], r['error']) for r in values}
    if normalize(outputs) != normalize(expected):
        raise ValueError('Serving answers differ from the imported HW6–7 evaluation')
