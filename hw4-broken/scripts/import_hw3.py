import argparse
import json
import shutil
from pathlib import Path

from src.config import load_params


def main() -> None:
    parser = argparse.ArgumentParser(description="Импортировать свой train/val из HW3")
    parser.add_argument("--hw3", type=Path, default=Path(__file__).resolve().parents[2] / "hw3-broken")
    parser.add_argument("--force", action="store_true", help="явно перезаписать уже импортированные файлы")
    args = parser.parse_args()
    cfg = load_params()["data"]
    targets = [Path(cfg["train_jsonl"]), Path(cfg["val_jsonl"])]
    sources = [args.hw3 / "data/train.jsonl", args.hw3 / "data/val.jsonl"]

    hw3_metrics = args.hw3 / "metrics/clean.json"
    if hw3_metrics.is_file():
        version = json.loads(hw3_metrics.read_text(encoding="utf-8")).get("version")
        if version != "v2":
            raise SystemExit(
                f"HW3 сейчас в версии {version!r}, нужна v2. "
                "Из hw3-broken выполните uv run python scripts/set_version.py v2 && make repro"
            )

    if all(p.is_file() and p.stat().st_size > 0 for p in targets) and not args.force:
        print("HW4: train/val JSONL уже существуют; не перезаписываю. --force для повторного импорта")
        return
    if any(p.exists() and p.stat().st_size > 0 for p in targets) and not args.force:
        raise SystemExit("В HW4 найден только один входной JSONL. Проверьте файлы или передайте --force")
    if not all(p.is_file() and p.stat().st_size > 0 for p in sources):
        raise SystemExit(
            f"Не найдены файлы split HW3: {sources}. "
            "Переключите HW3 на v2 и выполните make repro в hw3-broken"
        )

    for src in sources:
        with src.open(encoding="utf-8") as fh:
            head = next((line for line in fh if line.strip()), None)
            if not head:
                raise SystemExit(f"Пустой JSONL: {src}")
            sample = json.loads(head)
            if not {"id", "topic", "messages"} <= sample.keys():
                raise SystemExit(f"Не формат HW3 (id, topic, messages): {src}")
    for src, target in zip(sources, targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(src, tmp)
        tmp.replace(target)
        print(f"HW3: {src} -> {target} ({target.stat().st_size:,} bytes)")
    print("Датасет остаётся вне Git: data/ указан в .gitignore")


if __name__ == "__main__":
    main()
