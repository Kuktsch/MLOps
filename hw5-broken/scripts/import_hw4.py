from pathlib import Path
import shutil

src = Path("../hw4-broken/data/tokenized")
dst = Path("data/tokenized")
dst.mkdir(parents=True, exist_ok=True)
for name in ("train.pt", "val.pt"):
    source = src / name
    if not source.exists():
        raise SystemExit(f"Нет {source}. Сначала выполните tokenize в ДЗ 4.")
    shutil.copy2(source, dst / name)
    print(f"{source} -> {dst / name}")
