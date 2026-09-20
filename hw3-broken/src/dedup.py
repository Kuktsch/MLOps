"""Exact and near-duplicate detection over question-only lexical shingles.

LSH collects candidates; exact set Jaccard verifies them to avoid hash false
positives. Low LSH candidate threshold favours recall around 0.85 cut-off.
"""
from typing import Sequence

from datasketch import MinHash, MinHashLSH

from src.textnorm import normalize_text, shingles


def tokens(text: str, shingle_words: int) -> set[str]:
    return shingles(normalize_text(text), shingle_words)


def build_minhash(text: str, shingle_words: int, num_perm: int) -> MinHash:
    mh = MinHash(num_perm=num_perm)
    mh.update_batch([s.encode("utf-8") for s in sorted(tokens(text, shingle_words))])
    return mh


def exact_duplicates(keys: Sequence[str]) -> list[int]:
    seen: set[str] = set()
    dupes = []
    for i, key in enumerate(keys):
        if key in seen:
            dupes.append(i)
        else:
            seen.add(key)
    return dupes


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def near_duplicates(texts: Sequence[str], shingle_words: int, num_perm: int, threshold: float) -> list[int]:
    lsh = MinHashLSH(threshold=min(0.70, threshold), num_perm=num_perm)
    accepted: dict[str, set[str]] = {}
    dupes = []
    for i, text in enumerate(texts):
        sig = build_minhash(text, shingle_words, num_perm)
        grams = tokens(text, shingle_words)
        if any(jaccard(grams, accepted[k]) >= threshold for k in lsh.query(sig)):
            dupes.append(i)
        else:
            key = str(i)
            lsh.insert(key, sig)
            accepted[key] = grams
    return dupes


def cross_near_duplicates(left: Sequence[str], right: Sequence[str], shingle_words: int,
                          num_perm: int, threshold: float) -> list[tuple[int, int]]:
    lsh = MinHashLSH(threshold=min(0.70, threshold), num_perm=num_perm)
    left_sets: list[set[str]] = []
    for i, text in enumerate(left):
        lsh.insert(str(i), build_minhash(text, shingle_words, num_perm))
        left_sets.append(tokens(text, shingle_words))
    pairs = []
    for j, text in enumerate(right):
        grams = tokens(text, shingle_words)
        sig = build_minhash(text, shingle_words, num_perm)
        for key in lsh.query(sig):
            idx = int(key)
            if jaccard(left_sets[idx], grams) >= threshold:
                pairs.append((idx, j))
    return pairs
