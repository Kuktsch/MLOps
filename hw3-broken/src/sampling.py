"""Stable, nested answer-length-stratified sampling of real source examples.

Why: a compact wiki QA source has homogeneous answer lengths. Uniform SHA256
sampling gave 2591 valid v1 examples but p90/p10=420/281=1.49 (<1.6).
We enrich the *sampling* with naturally short/long answers from the existing
source. We do not change the diversity threshold or rewrite answer content.
"""

from collections import Counter
from math import ceil

from src.stats import spread


def select_balanced(candidates, rows, max_per_article, target_ratio):
    """Return (nested full ordering, sampling diagnostics).

    candidates: tuples (priority, source_key, record), priority-sorted.
    To preserve v1 subset of v2, produce ONE deterministic ordering up to v2,
    then caller takes [:rows[version]]. Five-slot schedule targets 20% short,
    20% long, 60% middle for both nested versions. Sampling strata are the
    2–10% most extreme source answers, depending on actual measured spread.
    """
    desired = max(rows.values())
    counts = sorted(set(rows.values()))
    if not candidates:
        raise ValueError("Нет кандидатов для сборки датасета")

    # For tiny offline regression fixtures the length diversity exercise is
    # inapplicable: avoid requiring hundreds of rows from a 5-row fixture.
    if desired < 100:
        selected = []
        per_article = Counter()
        for _priority, _key, record in candidates:
            article = record["topic"]
            if per_article[article] >= max_per_article:
                continue
            selected.append(record)
            per_article[article] += 1
            if len(selected) >= desired:
                break
        if len(selected) < desired:
            raise ValueError(f"Доступно только {len(selected)} из {desired} запрошенных примеров")
        return selected, {"method": "priority (tiny test fixture)", "source_tail_fraction": None,
                          "raw_answer_len_ratios": {name: spread([len(r["messages"][2]["content"]) for r in selected[:n]])["ratio_p90_p10"]
                                                    for name, n in rows.items()}}

    ordered_by_length = sorted(candidates, key=lambda item: (len(item[2]["messages"][2]["content"]), item[0]))
    n_all = len(candidates)
    best_diagnostics = None
    # reserve ≥8% slack in each tail against article-per-group capping
    min_tail_size = ceil(desired * 0.2 * 1.08)
    # Include longer/shorter source tails if the original QA has tightly
    # clustered answer lengths. Threshold is NEVER weakened.
    for fraction in (0.10, 0.08, 0.06, 0.04, 0.02):
        tail_size = max(ceil(n_all * fraction), min_tail_size)
        if 2 * tail_size >= n_all:
            continue
        short_ids = {item[1] for item in ordered_by_length[:tail_size]}
        long_ids = {item[1] for item in ordered_by_length[-tail_size:]}
        buckets = {"short": [], "middle": [], "long": []}
        for item in candidates:
            bucket = "short" if item[1] in short_ids else "long" if item[1] in long_ids else "middle"
            buckets[bucket].append(item)
        pointers = Counter()
        per_article = Counter()
        selected = []
        schedule = ("short", "middle", "long", "middle", "middle")
        exhausted = None
        while len(selected) < desired:
            bucket = schedule[len(selected) % len(schedule)]
            entries = buckets[bucket]
            i = pointers[bucket]
            while i < len(entries) and per_article[entries[i][2]["topic"]] >= max_per_article:
                i += 1
            pointers[bucket] = i + 1
            if i >= len(entries):
                exhausted = bucket
                break
            record = entries[i][2]
            selected.append(record)
            per_article[record["topic"]] += 1
        if exhausted is not None:
            best_diagnostics = f"недостаточно примеров в группе {exhausted!r} при fraction={fraction}"
            continue
        ratios = {name: spread([len(r["messages"][2]["content"]) for r in selected[:n]])["ratio_p90_p10"]
                  for name, n in rows.items()}
        if min(ratios.values()) >= target_ratio:
            return selected, {"method": "answer-length-stratified real-source sampling",
                              "source_tail_fraction": fraction, "tail_pool_size": tail_size,
                              "raw_answer_len_ratios": ratios,
                              "short_pool_answer_length_max": len(ordered_by_length[tail_size - 1][2]["messages"][2]["content"]),
                              "long_pool_answer_length_min": len(ordered_by_length[-tail_size][2]["messages"][2]["content"])}
        best_diagnostics = f"fraction={fraction}; raw ratios={ratios}, required={target_ratio}"
    raise ValueError("Реальный источник не даёт нужного разброса длины ответов: "
                     f"{best_diagnostics}. Не понижайте diversity.min_answer_len_ratio: "
                     "нужны дополнительные реальные примеры с более короткими/длинными ответами.")
