"""Build deterministic, nested Russian encyclopedia QA versions from pinned parquet.

The published compact final_qa_dataset.parquet has ONLY question, answer and
original_id. The full dataset has text/quality_prob, but they are OPTIONAL.
Never create a fake context or claim that an answer is context-grounded when the
source did not supply context. Group = Wikipedia article original_id.
"""
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from src.config import load_params, source_files
from src.sampling import select_balanced
from src.textnorm import normalize_text


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    cfg = load_params()
    rules, paths, source_cfg = cfg["collect"], cfg["paths"], cfg["source"]
    version = rules["version"]
    if version not in rules["rows"]:
        raise SystemExit(f"Неизвестная версия {version!r}")
    source = source_files(cfg)
    if len(source) != 1:
        raise SystemExit("Ожидался один локальный parquet-источник")
    started = time.perf_counter()
    pf = pq.ParquetFile(source[0])
    available = set(pf.schema_arrow.names)
    mandatory = {"question", "answer", "original_id"}
    if not mandatory <= available:
        raise SystemExit(f"В parquet отсутствуют поля: {sorted(mandatory - available)}; доступны {sorted(available)}")
    has_context = "text" in available
    cols = sorted(mandatory | ({"text"} if has_context else set()) |
                  ({"quality_prob"} if "quality_prob" in available else set()))
    candidates: list[tuple[str, str, dict]] = []
    stats = Counter()
    article_counts: Counter[str] = Counter()
    seen_source: set[str] = set()
    for batch in pf.iter_batches(batch_size=2048, columns=cols):
        for row in batch.to_pylist():
            stats["scanned"] += 1
            question, answer, article = (row.get(key) for key in ("question", "answer", "original_id"))
            text = row.get("text") if has_context else None
            required = (question, answer, article) + ((text,) if has_context else ())
            if any(not isinstance(x, str) or not x.strip() for x in required):
                stats["dropped_missing"] += 1
                continue
            question, answer, article = (x.strip() for x in (question, answer, article))
            if has_context:
                text = text.strip()
            if not ((not has_context or rules["min_context_chars"] <= len(text) <= rules["max_context_chars"])
                    and len(question) >= rules["min_question_chars"]
                    and rules["min_answer_chars"] <= len(answer) <= rules["max_answer_chars"]):
                stats["dropped_lengths"] += 1
                continue
            quality = row.get("quality_prob")
            if "quality_prob" in available and (quality is None or quality < rules["min_quality_prob"]):
                stats["dropped_quality"] += 1
                continue
            # Original source can contain several questions per paragraph; these are
            # distinct, but exactly repeated question+article pairs are not.
            source_key = digest(article + "\x00" + normalize_text(question))
            if source_key in seen_source:
                stats["dropped_source_duplicate"] += 1
                continue
            seen_source.add(source_key)
            # Compact source supplies no article paragraph. Do NOT fabricate one.
            user_content = (f"Контекст:\n{text}\n\nВопрос:\n{question}"
                            if has_context else question)
            record = {"id": "wiki_" + source_key[:24], "topic": article,
                      "messages": [
                          {"role": "system", "content": ""},
                          {"role": "user", "content": user_content},
                          {"role": "assistant", "content": answer},
                      ]}
            # Stable global sampling: sort article-wise to avoid order bias of parquet.
            priority = digest(str(rules["seed"]) + ":" + source_key)
            candidates.append((priority, source_key, record))
            article_counts[article] += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    desired = rules["rows"][version]
    prompts = rules["system_prompts"]
    if len(prompts) < 3:
        raise SystemExit("Для разнообразия укажите не менее трёх системных инструкций")
    # Select real source QA with a reproducible, length-stratified ordering.
    # We preserve v1 as a prefix of v2 and *never* loosen the diversity gate.
    try:
        sampled, sampling_info = select_balanced(
            candidates, rules["rows"], rules["max_examples_per_article"],
            target_ratio=float(cfg["diversity"]["min_answer_len_ratio"]) + 0.10,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    selected = sampled[:desired]
    per_article = Counter(record["topic"] for record in selected)
    keys_by_id = {item[2]["id"]: item[1] for item in candidates}
    for record in selected:
        source_key = keys_by_id[record["id"]]
        record["messages"][0]["content"] = prompts[int(digest(source_key), 16) % len(prompts)]
    outfile = Path(paths["raw"])
    outfile.parent.mkdir(parents=True, exist_ok=True)
    tmp = outfile.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in selected:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(outfile)
    result = {"version": version, "source": source_cfg["repository"],
              "source_revision": source_cfg["revision"], "source_sha256": source_cfg["sha256"],
              "source_columns": cols, "context_included": has_context,
              "quality_filter_applied": "quality_prob" in cols,
              "quality_threshold": rules["min_quality_prob"] if "quality_prob" in cols else None,
              "rows_scanned": stats["scanned"], "rows_written": len(selected),
              "eligible_candidates": len(candidates), "source_articles": len(article_counts),
              "selected_articles": len(per_article), "max_per_article": max(per_article.values()),
              "sampling": sampling_info,
              "system_prompt_variants": len({r["messages"][0]["content"] for r in selected}),
              **{k: stats[k] for k in ("dropped_missing", "dropped_lengths", "dropped_quality", "dropped_source_duplicate")},
              "seconds": round(time.perf_counter() - started, 2)}
    path = Path(paths["metrics_collect"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"collect: {version}: {len(selected)} / {len(candidates)} eligible, "
          f"{len(per_article)} Wikipedia-article groups, {result['system_prompt_variants']} system variants; "
          f"context={'yes' if has_context else 'NO (compact parquet)'}")


if __name__ == "__main__":
    main()
