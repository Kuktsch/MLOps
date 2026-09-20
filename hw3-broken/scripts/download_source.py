"""Download a pinned public parquet once; check SHA256 before publishing it.

The source stays in data/ and is a DVC output. Interrupted partials use .part.
"""
import hashlib
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from src.config import load_params


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    cfg = load_params()["source"]
    target = Path(cfg["output"])
    target.parent.mkdir(parents=True, exist_ok=True)
    want = cfg["sha256"].lower()
    if target.is_file():
        actual = sha256(target)
        if actual != want:
            raise SystemExit(f"Источник {target} имеет SHA256 {actual}, ожидался {want}; не используем подменённые данные")
        print(f"source: verified existing {target}, SHA256 {actual}")
        return
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, int(cfg["retries"]) + 1):
        try:
            req = urllib.request.Request(cfg["url"], headers={"User-Agent": "mlops-hw3/1.0"})
            with urllib.request.urlopen(req, timeout=120) as src, partial.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            actual = sha256(partial)
            if actual != want:
                partial.unlink(missing_ok=True)
                raise ValueError(f"SHA256 mismatch: {actual} != {want}")
            partial.replace(target)
            print(f"source: downloaded & SHA256 verified {target} ({target.stat().st_size:,} B)")
            return
        except (OSError, urllib.error.URLError, ValueError) as exc:
            partial.unlink(missing_ok=True)
            if attempt == int(cfg["retries"]):
                raise SystemExit(f"Не удалось скачать проверенный источник {cfg['url']}: {exc}\n"
                                 f"Можно загрузить файл вручную в {target} и повторить dvc repro") from exc
            print(f"download attempt {attempt}: {exc}; retrying")
            time.sleep(min(2 ** attempt, 8))


if __name__ == "__main__":
    main()
