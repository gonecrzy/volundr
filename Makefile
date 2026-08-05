.PHONY: backend-test documentation-audit compose-config up down

backend-test:
	cd backend && .venv/bin/python -m pytest -q

documentation-audit:
	PYTHONPATH=backend backend/.venv/bin/python backend/scripts/audit_repository.py

compose-config:
	docker compose config

up:
	docker compose up --build

down:
	docker compose down
