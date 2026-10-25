# Local development. `make dev` runs the review API and UI with no keys needed (recorded runs, CSV sheet,
# Slack outbox); put real credentials in .env to use the live API, Google Sheets and Slack instead.
PY ?= .venv/bin/python

.PHONY: setup dev seed api web test eval e2e

setup:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt
	cd web && npm install && npx playwright install chromium

seed:
	$(PY) -m server.seed

api:
	$(PY) -m uvicorn server.app:app --reload --port 8000

web:
	cd web && npx vite --port 5173

# API on :8000 and UI on http://localhost:5173 (seeds 12 recorded forms on first run)
dev:
	@test -f data/intake.db || $(PY) -m server.seed
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) -m uvicorn server.app:app --reload --port 8000 & \
	(cd web && npx vite --port 5173) & \
	wait

test:
	$(PY) -m unittest discover -s tests -t .

eval:
	$(PY) evals/run.py

e2e:
	cd web && npx playwright test
