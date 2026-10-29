"""Small release contracts. Standard library only; no model loading here."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cache_key(data_path: Path, config: dict) -> str:
    return digest(canonical({'data_sha256': file_digest(data_path), 'config': config}))


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('Manifest must be an object')
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Unsupported schema_version')
    for key in ('model_id', 'artifact_uri'):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f'Missing {key}')
    for key in ('model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        if not isinstance(manifest.get(key), str) or not re.fullmatch('[0-9a-f]{64}', manifest[key]):
            raise ValueError(f'Invalid {key}')
    runtime = manifest.get('runtime')
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('Missing runtime')
    try:
        actual = digest(canonical(runtime))
    except (TypeError, ValueError) as exc:
        raise ValueError('Runtime is not finite JSON') from exc
    if actual != manifest['runtime_sha256']:
        raise ValueError('Runtime hash mismatch')


def validate_release(manifest: dict, report: dict) -> None:
    validate_manifest(manifest)
    if not isinstance(report, dict) or report.get('status') != 'complete' or report.get('passed') is not True:
        raise ValueError('Incomplete or rejected evaluation')
    if not isinstance(report.get('evaluation_run_id'), str) or not report['evaluation_run_id'].strip():
        raise ValueError('Missing evaluation_run_id')
    for key in ('model_id', 'model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        if report.get(key) != manifest[key]:
            raise ValueError(f'Evaluation binding mismatch: {key}')
    metrics = report.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('Missing metrics')
    for key in ('accuracy', 'format_rate'):
        value = metrics.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'Invalid metric: {key}')
    try:
        canonical(report)
    except (ValueError,TypeError) as exc:
        raise ValueError('Report must be finite JSON') from exc


def manifest_bytes(manifest):
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False).encode('utf-8') + b'\n'


def atomic_bytes(target, payload):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.' + target.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        directory = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def atomic_json(target, value):
    atomic_bytes(target, manifest_bytes(value))


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    payload = manifest_bytes(manifest)
    target = Path(target)
    if target.exists() and target.read_bytes() == payload:
        return
    atomic_bytes(target, payload)
