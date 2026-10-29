"""FastAPI service. The loaded manifest is a snapshot, never the live pointer."""
import argparse
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from artifacts import verify_artifact
from model_backend import StubBackend, TransformersBackend
from release import validate_manifest


class ServiceState:
    def __init__(self, root, warmup_seconds=0, backend_factory=StubBackend, max_parallel=1):
        self.root = Path(root)
        self.ready = False
        self.error = None
        self.backend = None
        self.manifest = None
        self.warmup_finished = threading.Event()
        self.slots = threading.BoundedSemaphore(max_parallel)
        self.thread = threading.Thread(target=self.load, args=(warmup_seconds, backend_factory), daemon=True)
        self.thread.start()

    def load(self, seconds, factory):
        try:
            manifest = json.loads((self.root / 'accepted.json').read_text())
            validate_manifest(manifest)
            verify_artifact(manifest, self.root)
            if factory is TransformersBackend:
                from gate import verify_accepted
                verify_accepted(self.root, manifest)
            elif manifest.get('backend') == 'transformers':
                raise ValueError('A real manifest cannot be served by StubBackend')
            backend = factory(manifest, self.root)
            time.sleep(seconds)
            backend.warmup()
            self.manifest = manifest
            self.backend = backend
            self.warmup_finished.set()
            self.ready = True
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            print('LOAD_FAILED', self.error, flush=True)

    def generate(self, payload):
        started = time.perf_counter()
        if not isinstance(payload, dict) or set(payload) - {'prompt', 'max_new_tokens'}:
            raise HTTPException(422, 'Expected prompt and optional max_new_tokens only')
        prompt = payload.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8192:
            raise HTTPException(422, 'prompt must contain 1..8192 nonblank characters')
        limit = payload.get('max_new_tokens', 32)
        if type(limit) is not int:
            raise HTTPException(422, 'max_new_tokens must be an integer')
        if not self.ready:
            raise HTTPException(503, 'Model is loading or failed to load')
        fixed = self.manifest['runtime']['generation']['max_new_tokens']
        if limit != fixed:
            raise HTTPException(422, f'Only evaluated max_new_tokens={fixed} is supported')
        try:
            self.backend.validate_prompt(prompt)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not self.slots.acquire(timeout=30):
            raise HTTPException(429, 'Inference queue timeout')
        acquired = time.perf_counter()
        try:
            result = self.backend.generate(prompt, limit)
        finally:
            self.slots.release()
        finished = time.perf_counter()
        result.update(text=result['answer'], model_id=self.backend.loaded_id,
                      runtime_sha256=self.backend.runtime_sha256, request_id=str(uuid.uuid4()),
                      queue_seconds=acquired-started, generation_seconds=finished-acquired,
                      total_seconds=finished-started)
        return result


def create_app(root, warmup_seconds=0, backend_factory=StubBackend, debug=False):
    @asynccontextmanager
    async def lifespan(app):
        app.state.model = ServiceState(root, warmup_seconds, backend_factory)
        yield
        app.state.model.ready = False

    app = FastAPI(title='HW 8–10 accepted model', lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'alive': True, 'backend': backend_factory.label}

    @app.get('/ready')
    def ready():
        state = app.state.model
        payload = {'ready': state.ready}
        if state.ready:
            payload.update(model_id=state.backend.loaded_id, runtime_sha256=state.backend.runtime_sha256)
        return JSONResponse(payload, status_code=200 if state.ready else 503)

    if debug or backend_factory is StubBackend:
        @app.get('/debug')
        def diagnostics():
            state = app.state.model
            return {'loaded_id': state.backend.loaded_id if state.backend else None,
                    'calls': state.backend.calls if state.backend else 0,
                    'warmup_calls': state.backend.warmup_calls if state.backend else 0,
                    'warmup_finished': state.warmup_finished.is_set(), 'load_error': state.error}

    @app.post('/generate')
    async def generate(request: Request):
        # Stream with a hard cap, including chunked bodies without Content-Length.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413, 'Body too large')
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(400, 'Invalid JSON') from exc
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(app.state.model.generate, payload)

    return app


def main():
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument('--workspace', type=Path, default=Path('.lab'))
    p.add_argument('--port', type=int, default=8091)
    p.add_argument('--warmup-seconds', type=float, default=0)
    p.add_argument('--backend', choices=['stub', 'transformers'], default='stub')
    p.add_argument('--debug', action='store_true')
    args = p.parse_args()
    factory = StubBackend if args.backend == 'stub' else TransformersBackend
    uvicorn.run(create_app(args.workspace.resolve(), args.warmup_seconds, factory, args.debug),
                host='127.0.0.1', port=args.port, log_level='info')


if __name__ == '__main__':
    main()
