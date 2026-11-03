PY ?= .venv/bin/python

.PHONY: setup demo check test lint notebooks

setup:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --python 3.12 .venv && uv pip install --python $(PY) -e ".[dev]"; \
	else \
		python3 -m venv .venv && $(PY) -m pip install -e ".[dev]"; \
	fi

demo:
	$(PY) -m ontology_gate.demo --defect

check:
	$(PY) -m ontology_gate.checks

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

notebooks:
	$(PY) tools/make_student.py
