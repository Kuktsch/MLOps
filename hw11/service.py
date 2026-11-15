"""Continuation of HW 8–10 serving: verified snapshots and a CPU streaming backend."""

import asyncio
import json
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from artifacts import verify_artifact
from model_backend import StubBackend


BUCKETS = (.01, .025, .05, .075, .1, .15, .2, .3, .5, .75, 1, 1.5, 2, 3, 5, 10, 20, 30, 45)
TTFC = Histogram("api_ttfc_seconds", "Server send of first data fragment on completed streams", buckets=BUCKETS)
DURATION = Histogram("api_response_seconds", "Server duration of completed streams", buckets=BUCKETS)
QUEUE = Histogram("api_queue_seconds", "Queue time on completed streams", buckets=BUCKETS)
RUNNING = Gauge("api_running", "Requests holding an inference slot")
WAITING = Gauge("api_waiting", "Requests waiting for an inference slot")
READY = Gauge("api_ready", "Artifact verified and backend warmed")
RESULTS = Counter("api_requests_total", "Terminal request outcome", ["outcome"])
for outcome in ("completed", "rejected", "aborted"):
    RESULTS.labels(outcome)


def setting(name, default):
    return type(default)(os.getenv(name, default))


def event(kind, **data):
    print(json.dumps({"event": kind, "epoch": time.time(), **data}, ensure_ascii=False), flush=True)


class Generate(BaseModel, extra="forbid"):
    prompt: str = Field(min_length=1, max_length=8192, pattern=r"\S")
    history: list[Annotated[str, Field(max_length=1024)]] = Field(default_factory=list, max_length=8)
    session_id: str = Field(default="", max_length=96)
    prefix: str = Field(default="", max_length=96)
    chunks: int = Field(default=4, ge=1, le=32)
    chunk_delay_ms: int = Field(default=45, ge=0, le=1000)
    cpu_iterations: int = Field(default=0, ge=0, le=350000)


class SimulatedBackend(StubBackend):
    label = "simulated"

    def __init__(self, manifest, root):
        super().__init__(manifest, root)
        self.prefixes = OrderedDict()
        self.capacity = setting("CACHE_SIZE", 8)
        self.hit_seconds = setting("CACHE_HIT_MS", 8) / 1000
        self.miss_seconds = setting("CACHE_MISS_MS", 60) / 1000

    def get_prefix(self, prefix):
        hit = prefix in self.prefixes
        self.prefixes[prefix] = None
        self.prefixes.move_to_end(prefix)
        if len(self.prefixes) > self.capacity:
            self.prefixes.popitem(last=False)
        return hit

    async def chunk(self, iterations, delay):
        if iterations:
            await asyncio.to_thread(pbkdf2_hmac, "sha256", b"hw11-cpu", b"fixed-salt", iterations)
        await asyncio.sleep(delay)


class State:
    def __init__(self):
        self.pod = setting("POD_NAME", "local")
        self.root = Path(setting("MODEL_ROOT", "/app/models"))
        self.version = setting("MODEL_VERSION", "A")
        self.warmup_seconds = setting("WARMUP_SECONDS", 20.0)
        self.max_waiting = setting("MAX_WAITING", 12)
        self.queue_timeout = setting("QUEUE_TIMEOUT_SECONDS", 3.0)
        self.max_parallel = setting("MAX_PARALLEL", 1)
        self.slots = asyncio.Semaphore(self.max_parallel)
        self.waiting = 0
        self.running = 0
        self.backend = None
        self.model_hash = ""
        self.ready = False

    async def load(self):
        event("warmup_start", pod=self.pod, version=self.version)
        try:
            manifest = json.loads((self.root / f"manifest-{self.version.lower()}.json").read_text())
            if manifest["model_id"] != self.version:
                raise ValueError("Configured and verified versions differ")
            verify_artifact(manifest, self.root)
            if os.getenv("FAIL_LOAD") == "true":
                raise ValueError("Injected load failure")
            self.model_hash = next(iter(manifest["file_hashes"].values()))
            self.backend = SimulatedBackend(manifest, self.root)
            await asyncio.sleep(self.warmup_seconds)
            await asyncio.to_thread(self.backend.warmup)
            self.ready = True
            READY.set(1)
            event("warmup_complete", pod=self.pod, version=self.version, sha256=self.model_hash)
        except (OSError, ValueError, KeyError) as exc:
            event("load_failed", pod=self.pod, version=self.version, reason=str(exc))

    def identity(self):
        return {
            "pod": self.pod, "version": self.backend.loaded_id if self.backend else "",
            "configured_version": self.version, "model_sha256": self.model_hash,
            "backend_mode": "simulated", "ready": self.ready,
        }


@asynccontextmanager
async def lifespan(app):
    app.state.model = state = State()
    READY.set(0)
    task = asyncio.create_task(state.load())
    try:
        yield
    finally:
        state.ready = False
        READY.set(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        event("shutdown", pod=state.pod, version=state.version)


app = FastAPI(title="HW 11 simulated streaming API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"alive": True}


@app.get("/startup")
def startup(request: Request):
    state = request.app.state.model
    return JSONResponse(state.identity(), status_code=200 if state.ready else 503)


@app.get("/ready")
def ready(request: Request):
    return startup(request)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/generate")
async def generate(body: Generate, request: Request):
    state = request.app.state.model
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", str(uuid4()))[:96]
    identity = state.identity()
    headers = {
        "X-Request-ID": request_id, "X-Pod": state.pod, "X-Version": identity["version"],
        "X-Model-SHA256": identity["model_sha256"], "X-Backend-Mode": "simulated",
        "X-Backend-Ready": str(identity["ready"]).lower(),
        "X-Client-IP": request.client.host,
    }
    common = {**identity, "request_id": request_id, "session_id": body.session_id,
              "client_ip": request.client.host}
    event("request_received", **common)

    def reject(status, reason):
        RESULTS.labels("rejected").inc()
        event("request_finished", **common, outcome="rejected", status=status, reason=reason)
        return JSONResponse({**identity, "request_id": request_id, "error": reason},
                            status_code=status, headers=headers)

    if not state.ready:
        return reject(503, "warming")
    if state.slots.locked() and state.waiting >= state.max_waiting:
        return reject(429, "queue_full")

    state.waiting += 1
    WAITING.inc()
    try:
        await asyncio.wait_for(state.slots.acquire(), state.queue_timeout)
    except TimeoutError:
        return reject(429, "queue_timeout")
    finally:
        state.waiting -= 1
        WAITING.dec()

    queue_seconds = time.perf_counter() - started
    state.running += 1
    RUNNING.inc()
    backend = state.backend
    hit = backend.get_prefix(body.prefix or body.prompt)
    headers.update({
        "X-Queue-Seconds": f"{queue_seconds:.6f}", "X-Cache-Hit": str(hit).lower(),
    })

    async def stream():
        first = None
        count = 0
        outcome = "aborted"
        try:
            await asyncio.sleep(backend.hit_seconds if hit else backend.miss_seconds)
            for index in range(1, body.chunks + 1):
                await backend.chunk(body.cpu_iterations, body.chunk_delay_ms / 1000)
                fragment = {"index": index, "request_id": request_id, "backend_mode": "simulated",
                            "text": " | ".join([*body.history, body.prompt]) if index == 1 else f"part {index}"}
                count += 1
                if first is None:
                    first = time.perf_counter() - started
                yield json.dumps(fragment, ensure_ascii=False) + "\n"
            finished = time.perf_counter() - started
            yield json.dumps({"done": True, "request_id": request_id, "chunks": count}) + "\n"
            TTFC.observe(first)
            DURATION.observe(finished)
            QUEUE.observe(queue_seconds)
            outcome = "completed"
        finally:
            state.running -= 1
            state.slots.release()
            RUNNING.dec()
            RESULTS.labels(outcome).inc()
            event("request_finished", **common, outcome=outcome, status=200, chunks=count,
                  queue_seconds=queue_seconds, ttfc_seconds=first, cache_hit=hit)

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers=headers)
