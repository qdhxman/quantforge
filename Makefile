.PHONY: help install test parity web serve clean

help:
	@echo "make install  - pip install -e .[dev,api]"
	@echo "make test     - run unit tests"
	@echo "make parity   - verify Python vs JavaScript engine"
	@echo "make web      - regenerate web/data.js and web/presets.js"
	@echo "make serve    - start API on 127.0.0.1:8000"

install:
	pip install -e '.[dev,api]'

test:
	python -m unittest discover -s tests -v

parity:
	python scripts/verify_parity.py
	node scripts/verify_parity.js

web:
	python -m quantforge sample-data

serve:
	python -m quantforge serve --port 8000

clean:
	python -c "import shutil,pathlib; [shutil.rmtree(p,ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
