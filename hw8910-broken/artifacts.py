"""Rehash actual local artifacts before publication AND before model loading."""
from pathlib import Path
from release import canonical, digest, file_digest, validate_manifest


def local_path(root, uri):
    path = Path(uri.removeprefix('file://'))
    return path.resolve() if path.is_absolute() else (Path(root) / path).resolve()


def verify_artifact(manifest, root):
    validate_manifest(manifest)
    hashes = manifest.get('file_hashes')
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('Missing pinned model files')
    artifact = local_path(root, manifest['artifact_uri'])
    base = artifact if artifact.is_dir() else artifact.parent
    for name, expected in hashes.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe artifact path')
        path = (base / relative).resolve()
        # HF snapshots intentionally use symlinks to content-addressed blobs.
        if file_digest(path) != expected:
            raise ValueError(f'Artifact file changed: {name}')
    if digest(canonical(hashes)) != manifest['model_sha256']:
        raise ValueError('Model aggregate hash mismatch')
    runtime = manifest['runtime']
    for section, uri_key, hash_key in [('tokenizer_files', 'tokenizer_uri', 'tokenizer_sha256'),
                                      ('base_files', 'base_uri', 'base_files_sha256')]:
        if section not in runtime:
            if manifest.get('backend') == 'transformers':
                raise ValueError(f'Missing {section}')
            continue
        files = runtime[section]
        source = local_path(root, runtime[uri_key])
        if not files or digest(canonical(files)) != runtime[hash_key]:
            raise ValueError(f'Invalid {section}')
        for name, expected in files.items():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe runtime file path')
            if file_digest(source / name) != expected:
                raise ValueError(f'Runtime file changed: {name}')
    if manifest.get('backend') == 'transformers':
        if len(runtime.get('base_revision', '')) != 40:
            raise ValueError('Base revision must be a commit')
        if runtime['base_revision'] != Path(runtime['base_uri']).name:
            raise ValueError('Base snapshot does not match revision')
        if runtime.get('backend_code_sha256') != file_digest(Path(__file__).with_name('model_backend.py')):
            raise ValueError('Generation implementation changed: reevaluate')
    return artifact
