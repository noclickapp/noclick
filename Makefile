.PHONY: local install test test-backend test-backend-community test-frontend typecheck generate-types build check-community-boundary

local:
	python backend/scripts/run_local.py

install:
	pip install -r requirements-dev.txt
	cd frontend && pnpm install --frozen-lockfile

test: test-backend typecheck build test-frontend

test-backend:
	cd backend && python -m pytest tests --tb=short

# Hermetic suite used by community CI. The complete suite additionally includes
# integration tests that require configured third-party sandboxes and services.
test-backend-community:
	# The whole suite, not a list of files. It used to be a list, and the list
	# is why nobody noticed that twenty tables the code queries had been dropped
	# from the shipped schema: none of the tests that touch them were on it.
	# Tests needing a live third-party credential skip themselves when it is
	# absent, so this is green without any secrets.
	# DB-backed items are placed in one xdist group by tests/conftest.py. This
	# keeps one shared PostgreSQL testcontainer instead of starting one per CPU,
	# while the much larger unit-test lane still uses all available workers.
	cd backend && python -m pytest tests nodes/tests --tb=short -n auto --dist loadgroup

test-frontend:
	cd frontend && pnpm test

typecheck:
	cd frontend && pnpm typecheck

generate-types:
	cd backend && python scripts/generate_socket_types.py

build:
	cd frontend && pnpm build

check-community-boundary:
	bash scripts/check-community-boundary.sh
