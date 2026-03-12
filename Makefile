.PHONY: setup dev test clean

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

setup: $(VENV)/bin/activate  ## Create venv and install all dependencies
	@echo "✅ Setup complete. Run: source venv/bin/activate"

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@touch $(VENV)/bin/activate

dev: setup  ## Start the backend + frontend dev servers
	$(PYTHON) -m uvicorn server.app:app --reload --port 8000 &
	cd web && npm run dev

test: setup  ## Run all tests
	$(PYTHON) -m pytest tests/ -v

clean:  ## Remove venv and caches
	rm -rf $(VENV) .pytest_cache __pycache__ _scratch
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
