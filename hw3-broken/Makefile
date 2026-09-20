.PHONY: install source repro report v1 v2 versions diff dag diversity contamination check clean

install:
	uv sync

source:
	uv run dvc repro source

repro:
	uv run dvc repro
	uv run python -m scripts.write_datasheet

report:
	uv run python -m scripts.write_datasheet

v1:
	uv run python scripts/set_version.py v1
	$(MAKE) repro

v2:
	uv run python scripts/set_version.py v2
	$(MAKE) repro

versions:
	bash scripts/build_versions.sh

diff:
	uv run dvc metrics diff HEAD~1 HEAD

dag:
	uv run dvc dag

diversity:
	uv run python -m src.diversity

contamination:
	uv run python scripts/check_contamination.py

check:
	bash tests/check.sh

clean:
	rm -rf data/ metrics/*.json params.yaml.bak params.yaml.orig
