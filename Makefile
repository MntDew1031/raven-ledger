.PHONY: dev build test compose-up compose-down

dev:
	npm run dev

build:
	npm run build

test:
	npm test

compose-up:
	docker compose pull
	docker compose up -d

compose-down:
	docker compose down
