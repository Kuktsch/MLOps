.PHONY: install sample import-hw3 calibrate prepare tokenize repro check clean

install:
	uv sync --python 3.12

# Взять настоящий split v2 из соседней HW3; не перезаписывает существующие JSONL.
import-hw3:
	uv run python -m scripts.import_hw3

# Подобрать max_seq_len по реальному распределению токенов обоих сплитов.
calibrate:
	uv run python -m scripts.calibrate_max_seq_len

prepare: import-hw3 calibrate

# Только для преподавателя: его parquet -> JSONL. Студент использует import-hw3.
sample:
	uv run python -m scripts.make_sample

tokenize:
	uv run python -m src.tokenize_data

repro:
	uv run dvc repro

check:
	bash tests/check.sh

# Не удаляет входные данные из HW3 или сохранённые отчёты.
clean:
	rm -rf data/tokenized
