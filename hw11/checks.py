"""Own integration checks. The orchestration runs these inside client Pods."""

import argparse
import concurrent.futures
import json
import time

from client import attempt


def version(target, expected, label, **kwargs):
    row = attempt(target, {"prompt": label}, label)
    assert row["outcome"] == "completed", row
    assert row["backend_mode"] == "simulated" and row["ready"] == "true", row
    assert row["version"] == expected and row["model_sha256"] == kwargs["sha256"], row
    if kwargs.get("old_pod"):
        assert row["pod"] != kwargs["old_pod"], row
    return row


def dialogue(target):
    def call(name, marker, history):
        return attempt(target, {"session_id": name, "prompt": marker, "history": history,
                                "chunks": 1}, f"dialogue-{name}-{marker}")

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        rows = [pool.submit(call, "blue", "BLUE-2", ["BLUE-1"]),
                pool.submit(call, "orange", "ORANGE-2", ["ORANGE-1"])]
        blue, orange = [job.result() for job in rows]
    assert blue["outcome"] == orange["outcome"] == "completed", (blue, orange)
    assert blue["text"] == "BLUE-1 | BLUE-2" and orange["text"] == "ORANGE-1 | ORANGE-2", (blue, orange)
    return [blue, orange]


def overload(target):
    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        rows = list(pool.map(lambda n: attempt(
            target, {"prompt": "overload", "chunks": 4, "chunk_delay_ms": 100},
            f"check-overload-{n}"), range(20)))
    assert any(row["status"] == 429 and row["outcome"] == "rejected" for row in rows), rows
    return rows


def warmup(target, expect_early):
    rows = []
    for n in range(35):
        row = attempt(target, {"prompt": "warmup check", "chunks": 1}, f"warmup-{'bad' if expect_early else 'fixed'}-{n}",
                      timeout=1)
        rows.append(row)
        time.sleep(.85)
    early = [row for row in rows if row.get("ready") == "false" and row.get("status") == 503]
    assert bool(early) == expect_early and any(row["outcome"] == "completed" for row in rows), rows
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("check", choices=["version", "dialogue", "overload", "warmup", "stream"])
    parser.add_argument("target")
    parser.add_argument("--version", default="A")
    parser.add_argument("--sha256")
    parser.add_argument("--old-pod")
    parser.add_argument("--label", default="check-version")
    parser.add_argument("--expect-early", action="store_true")
    args = parser.parse_args()
    if args.check == "version":
        rows = [version(args.target, args.version, args.label, sha256=args.sha256, old_pod=args.old_pod)]
    elif args.check == "warmup":
        rows = warmup(args.target, args.expect_early)
    elif args.check == "dialogue":
        rows = dialogue(args.target)
    elif args.check == "overload":
        rows = overload(args.target)
    else:
        def first(row):
            print(json.dumps(dict(row, signal="first_fragment")), flush=True)

        rows = [attempt(args.target, {"prompt": "long response", "history": ["PREVIOUS-STATE"],
                                     "session_id": "replacement-dialogue", "chunks": 32, "chunk_delay_ms": 950},
                        args.label, first_fragment=first)]
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
