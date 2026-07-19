# Convenience wrapper around the Docker sandbox. Run `make help` for the list.
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build (if needed) and start app + postgres + redis in the background
	docker compose up -d --build

shell: ## Open a shell inside the app sandbox
	docker compose exec app bash

run: ## Run a lesson file, e.g. make run FILE=phases/00-foundations/01-bits-and-bytes/code/bits_and_bytes.py
	docker compose exec app python $(FILE)

test: ## Run pytest inside the sandbox
	docker compose exec app pytest

logs: ## Tail logs from all services
	docker compose logs -f

down: ## Stop everything (keeps the database volume)
	docker compose down

clean: ## Stop everything AND wipe the database volume
	docker compose down -v

site: ## Rebuild the website data (data.js) from the lesson folders
	node site/build.js

.PHONY: help up shell run test logs down clean site
