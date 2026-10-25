import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import yaml

REPORT_DOCUMENTS = (
    'comparison.csv', 'conclusion.md', 'defects.md', 'data.md',
)
REPORT_METRICS = (
    'sweep.json', 'candidate-model.json', 'baseline-outputs.json', 'candidate-outputs.json',
    'baseline-eval.json', 'candidate-eval.json', 'eval-diff.json', 'quality-gate.json',
    'negative-outputs.json', 'negative-gate.json', 'storage-check.json',
    'base-weights-check.json', 'dvc-check.json', 'evidence.json',
    'preflight.json', 'pre-evaluation.json', 'dvc-restore-check.json',
    'data-provenance.json', 'tokenization-proof.json', 'leakage-review.json',
)
REPORT_LOGS = ('sweep.log', 'evaluate.log', 'eval-gate.log', 'check-negative.log',
               'check-storage.log', 'check-all.log')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draft', action='store_true', help='Упаковать доступные материалы и перечислить недостающие')
    args = parser.parse_args()
    root = Path.cwd()
    required = ['metrics/sweep.json', 'docs/comparison.csv', 'evaluation/baseline.json',
                'metrics/baseline-outputs.json', 'metrics/candidate-outputs.json',
                'metrics/baseline-eval.json', 'metrics/candidate-eval.json', 'metrics/eval-diff.json',
                'metrics/quality-gate.json', 'metrics/negative-gate.json', 'metrics/storage-check.json']
    missing = [p for p in required if not (root / p).is_file()]
    if missing and not args.draft:
        raise SystemExit('Комплект ещё не завершён: ' + ', '.join(missing) + '. Для черновика: make submission-draft')
    reports = root / 'submission/reports'
    reports.mkdir(parents=True, exist_ok=True)
    included = {'checksums.json', 'status.json'}
    for directory, names in [('metrics', REPORT_METRICS + REPORT_LOGS), ('docs', REPORT_DOCUMENTS)]:
        for name in names:
            path = root / directory / name
            if path.is_file():
                shutil.copyfile(path, reports / name)
                included.add(name)
    for path in [root / 'evaluation/params.json', root / 'evaluation/baseline.json']:
        if path.exists():
            name = 'evaluation-' + path.name
            shutil.copyfile(path, reports / name)
            included.add(name)
    for path in reports.iterdir():
        if path.is_file() and path.name not in included:
            path.unlink()
    (reports / 'status.json').write_text(json.dumps(dict(status='draft' if missing else 'complete',
        missing=missing),
        ensure_ascii=False, indent=2) + '\n')
    checksums = {str(p.relative_to(reports)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(reports.iterdir()) if p.is_file() and p.name != 'checksums.json'}
    (reports / 'checksums.json').write_text(json.dumps(checksums, indent=2) + '\n')
    with zipfile.ZipFile(root / 'submission/reports.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(reports.iterdir()):
            archive.write(p, 'reports/' + p.name)
    entry = yaml.safe_load((root / 'data/eval.dvc').read_text())['outs'][0]['md5']
    remote = root / '.dvc-storage/files/md5'
    directory = remote / entry[:2] / entry[2:]
    hashes = [entry] + [row['md5'] for row in json.loads(directory.read_text())]
    with zipfile.ZipFile(root / 'submission/evaluation-data.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in sorted((root / 'data/eval').iterdir()):
            if p.is_file():
                archive.write(p, str(p.relative_to(root)))
        archive.write(root / 'data/eval.dvc', 'data/eval.dvc')
        for value in hashes:
            p = remote / value[:2] / value[2:]
            archive.write(p, str(p.relative_to(root)))
    print(('Черновик; ' if missing else 'Полный комплект; ') +
          'submission/reports.zip; submission/evaluation-data.zip (без весов и тензоров)')


if __name__ == '__main__':
    main()
