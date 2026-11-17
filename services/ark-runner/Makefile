.DEFAULT_GOAL := help

VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: help init test lint build

help: # show help for each of the Makefile recipes
	@grep -E '^[a-zA-Z0-9 -]+:.*#'  Makefile | sort | while read -r l; do printf "\033[1;32m$$(echo $$l | cut -f 1 -d':')\033[00m:$$(echo $$l | cut -f 2- -d'#')\n"; done

init: # create a venv and install the runner with test + adapter extras
	uv venv $(VENV)
	ARK_SDK_WHL=$$(ls ../../out/ark-sdk/py-sdk/dist/ark_sdk-*.whl 2>/dev/null | sort -V | tail -1); \
	if [ -n "$$ARK_SDK_WHL" ]; then VIRTUAL_ENV=$(VENV) uv pip install "$$ARK_SDK_WHL"; fi
	VIRTUAL_ENV=$(VENV) uv pip install -e ".[test]"

test: # run unit tests
	PYTHONPATH=src $(PY) -m pytest tests/ -q

lint: # ruff check
	$(PY) -m ruff check src tests

build: # build Docker image (from repo root; needs the prebuilt ark-sdk wheel)
	@$(MAKE) -C ../.. ark-runner-build
