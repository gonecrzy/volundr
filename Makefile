.PHONY: backend-test compose-config up down

backend-test:
	cd backend && .venv/bin/python -m pytest -q

compose-config:
	docker compose config

up:
	docker compose up --build

down:
	docker compose down
