PYTHON ?= .venv/bin/python
HW67_PROJECT ?= ../mlops26-hw6-7/hw67-broken
REAL_WORKSPACE ?= .real-synced
EVALUATION_EVIDENCE ?= evidence/model-synced
BENCHMARK_OUTPUT ?= evidence/synced-api/benchmark
.PHONY: setup check check-hw67 check-all unit check-negative demo-flow real-prepare real-baseline real-candidate real-api benchmark
setup:
	uv sync --frozen
unit:
	python3 -m unittest discover -s tests -p test_release.py -v
check:
	$(PYTHON) -m compileall -q release.py lab.py service.py model_backend.py artifacts.py publication.py flow.py gate.py hw67_import.py rollback.py scripts tests vendor
	$(PYTHON) -m unittest discover -s tests -v
check-hw67:
	$(MAKE) -C $(HW67_PROJECT) check-eval
check-all: check check-hw67
check-negative:
	$(PYTHON) scripts/check_negative.py
demo-flow:
	$(PYTHON) scripts/demo_flow.py
real-prepare:
	uv sync --frozen --extra model
	$(PYTHON) scripts/prepare_real.py --hw67 $(HW67_PROJECT) --workspace $(REAL_WORKSPACE) --evidence $(EVALUATION_EVIDENCE)
real-baseline:
	$(PYTHON) flow.py --workspace $(REAL_WORKSPACE) --manifest manifest-baseline.json --report release-report-baseline.json
real-candidate:
	$(PYTHON) flow.py --workspace $(REAL_WORKSPACE) --manifest manifest-candidate.json --report release-report.json
real-api:
	HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 $(PYTHON) service.py --workspace $(REAL_WORKSPACE) --backend transformers --port 8091
benchmark:
	$(PYTHON) scripts/benchmark.py --prompts $(EVALUATION_EVIDENCE)/golden.jsonl --output $(BENCHMARK_OUTPUT)
