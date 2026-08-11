.PHONY: dev build test test-frontend test-backend compose-up compose-down

dev:
	npm run dev

build:
	npm run build

test: test-frontend test-backend

test-frontend:
	npm test

test-backend:
	cd backend && ruff check . && python -m pytest -q

compose-up:
	docker compose pull
	docker compose up -d

compose-down:
	docker compose down
