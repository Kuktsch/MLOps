"""Group-disjoint 80/10/10 split by Wikipedia article (original_id)."""
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from src.config import load_params
from src.contamination import is_clean, report
from src.schema import Example, dump, iter_examples
from src.textnorm import normalize_group


def assign_groups(groups: dict[str, list[Example]], ratios: dict[str, float], seed: int) -> dict[str, list[Example]]:
    if not groups or not ratios or any(x <= 0 for x in ratios.values()):
        raise ValueError("Пустые группы или неверные доли сплита")
    if abs(sum(ratios.values()) - 1) > 1e-6:
        raise ValueError(f"Доли сплита должны давать 1, получено {ratios}")
    # Best-fit group-aware allocation; deterministic sort independent of input order.
    ordered = sorted(groups, key=lambda g: (-len(groups[g]), hashlib.sha256(f"{seed}:{g}".encode()).hexdigest()))
    sizes = {k: 0 for k in ratios}
    buckets: dict[str, list[Example]] = {k: [] for k in ratios}
    total = sum(map(len, groups.values()))
    for group in ordered:
        # Minimize squared normalized deviation from desired per-split size.
        # This also fills val/test instead of sending all early groups to train.
        def score(name: str) -> tuple[float, float, int]:
            target = total * ratios[name]
            after = sizes[name] + len(groups[group])
            return ((after - target) / target, sizes[name] / target, list(ratios).index(name))
        under = [name for name in ratios if sizes[name] < total * ratios[name]]
        name = min(under or list(ratios), key=score)
        buckets[name].extend(groups[group])
        sizes[name] += len(groups[group])
    return buckets


def main() -> None:
    params = load_params()
    paths, cfg = params["paths"], params["split"]
    started = time.perf_counter()
    examples = list(iter_examples(paths["clean"]))
    if cfg["group_key"] != "topic":
        raise SystemExit(f"неизвестный split.group_key: {cfg['group_key']!r}")
    grouped: dict[str, list[Example]] = defaultdict(list)
    for ex in examples:
        grouped[normalize_group(ex.topic)].append(ex)
    buckets = assign_groups(grouped, cfg["ratios"], cfg["seed"])
    nd = params["clean"]["near_dup"]
    rep = report(buckets["train"], buckets["test"], shingle_words=nd["shingle_words"],
                 num_perm=nd["num_perm"], threshold=params["contamination"]["threshold"])
    if not is_clean(rep):
        raise SystemExit(f"split: контаминация train/test, артефакты не перезаписаны: {rep}")
    # Additional val overlaps by id, question, and article group.
    for a, b in (("train", "val"), ("val", "test")):
        aa, bb = buckets[a], buckets[b]
        if ({ex.id for ex in aa} & {ex.id for ex in bb}) or ({normalize_group(ex.topic) for ex in aa} & {normalize_group(ex.topic) for ex in bb}):
            raise SystemExit(f"split: контаминация {a}/{b} по id или статье")
    for name, rows in buckets.items():
        out = Path(paths[name])
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_suffix(".jsonl.tmp")
        with temp.open("w", encoding="utf-8") as fh:
            for ex in rows:
                fh.write(dump(ex) + "\n")
        temp.replace(out)
    metrics = {
        "version": params["collect"]["version"], "seed": cfg["seed"],
        "group_key": cfg["group_key"], "groups_total": len(grouped),
        "sizes": {name: len(rows) for name, rows in buckets.items()},
        "groups": {name: len({normalize_group(ex.topic) for ex in rows}) for name, rows in buckets.items()},
        "ratios_actual": {name: round(len(rows) / len(examples), 4) for name, rows in buckets.items()},
        "contamination": rep, "seconds": round(time.perf_counter() - started, 2),
    }
    mpath = Path(paths["metrics_split"])
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("split: " + ", ".join(f"{name} {len(rows)}" for name, rows in buckets.items()) + f"; {len(grouped)} article groups; leakage=0")


if __name__ == "__main__":
    main()
