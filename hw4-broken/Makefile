.PHONY: install sample import-hw3 calibrate prepare tokenize repro check clean

install:
	uv sync --python 3.12

import-hw3:
	uv run python -m scripts.import_hw3

calibrate:
	uv run python -m scripts.calibrate_max_seq_len

prepare: import-hw3 calibrate

# Стадия 0, только для преподавателя: parquet курса -> data/train.jsonl, data/val.jsonl.
# У студента вход другой — его датасет из ДЗ 3, положенный в те же файлы.
sample:
	uv run python -m scripts.make_sample

# Стадия tokenize: JSONL -> токенизированный датасет + метрики + отчёт.
# Та же команда объявлена стадией в dvc.yaml — оттуда её и запускает dvc repro.
tokenize:
	uv run python -m src.tokenize_data

repro:
	uv run dvc repro

check:
	bash tests/check.sh

clean:
	rm -rf data/tokenized
