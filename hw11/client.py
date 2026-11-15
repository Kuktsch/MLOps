"""Open-loop HTTP load generator. Each attempt uses a separate TCP connection."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
import socket
import time
from urllib.parse import urlsplit


def attempt(target, payload, request_id, timeout=40, first_fragment=None):
    url = urlsplit(target)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    row = {"request_id": request_id, "sent_ns": time.monotonic_ns(), "sent_epoch": time.time(),
           "status": None, "first_ns": None, "parts": 0, "fragment_ns": [], "outcome": "aborted"}
    try:
        conn.request("POST", "/generate", json.dumps(payload),
                     {"Content-Type": "application/json", "X-Request-ID": request_id, "Connection": "close"})
        response = conn.getresponse()
        row.update(status=response.status, pod=response.getheader("X-Pod"),
                   version=response.getheader("X-Version"), model_sha256=response.getheader("X-Model-SHA256"),
                   backend_mode=response.getheader("X-Backend-Mode"), ready=response.getheader("X-Backend-Ready"),
                   client_ip=response.getheader("X-Client-IP"), cache_hit=response.getheader("X-Cache-Hit"),
                   queue_seconds=float(response.getheader("X-Queue-Seconds", "nan")))
        if math.isnan(row["queue_seconds"]):
            row["queue_seconds"] = None
        if response.status != 200:
            row.update(outcome="rejected", detail=response.read().decode(errors="replace"))
            return row
        for line in response:
            now = time.monotonic_ns()
            fragment = json.loads(line)
            if fragment["request_id"] != request_id:
                raise ValueError("mismatched request ID")
            if fragment.get("done"):
                if row["parts"] == fragment["chunks"] == payload.get("chunks", 4):
                    row["outcome"] = "completed"
                else:
                    row["detail"] = "incorrect final fragment count"
                break
            if fragment["index"] != row["parts"] + 1:
                raise ValueError("incorrect fragment order")
            row["parts"] += 1
            row["fragment_ns"].append(now)
            if row["first_ns"] is None:
                row.update(first_ns=now, text=fragment["text"])
                if first_fragment:
                    first_fragment(row)
    except (TimeoutError, socket.timeout) as exc:
        row.update(outcome="timed_out", detail=str(exc))
    except (OSError, http.client.HTTPException, ValueError, KeyError) as exc:
        row["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        row.update(finished_ns=time.monotonic_ns(), finished_epoch=time.time())
        conn.close()
    return row


def schedule(args):
    for seq in range(int(args.duration * args.rate)):
        owner = seq % 4
        if args.traffic == "skew":
            owner = 0 if seq % 15 < 12 else seq % 15 - 11
        if args.traffic == "solo":
            owner = 0
        if owner == args.client:
            yield seq, args.start + seq / args.rate, owner


async def run(args):
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=96))
    start_ns = time.monotonic_ns() + round((args.start - time.time()) * 1e9)
    rows = []

    async def issue(seq, planned_epoch, owner):
        planned_ns = start_ns + round((planned_epoch - args.start) * 1e9)
        await asyncio.sleep(max(0, (planned_ns - time.monotonic_ns()) / 1e9))
        request_id = f"{args.run}-{seq:05}"
        payload = {"prompt": f"shape-{seq % 8:02}", "prefix": f"{args.cache_epoch}-{owner}",
                   "session_id": f"client-{owner}", "chunks": args.chunks,
                   "chunk_delay_ms": args.chunk_delay, "cpu_iterations": args.cpu_iterations}
        result = await asyncio.to_thread(attempt, args.target, payload, request_id, args.timeout)
        row = {**result, "run": args.run, "seq": seq, "client": owner, "target": args.target,
               "traffic": args.traffic, "planned_epoch": planned_epoch, "planned_ns": planned_ns, "payload": payload}
        print(json.dumps(row, ensure_ascii=False), flush=True)

    for seq, epoch, owner in schedule(args):
        rows.append(asyncio.create_task(issue(seq, epoch, owner)))
    await asyncio.gather(*rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--cache-epoch", required=True)
    parser.add_argument("--client", type=int, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--rate", type=float, default=8)
    parser.add_argument("--traffic", choices=["even", "skew", "solo"], default="even")
    parser.add_argument("--chunks", type=int, default=4)
    parser.add_argument("--chunk-delay", type=int, default=45)
    parser.add_argument("--cpu-iterations", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=40)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
