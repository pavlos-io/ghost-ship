.PHONY: build smoke smoke-gh up app worker cli dev logs test lint

build:
	docker build -f Dockerfile.sandbox -t agent-sandbox:latest .

smoke: build
	docker run --rm -e CLAUDE_CODE_OAUTH_TOKEN=$$CLAUDE_CODE_OAUTH_TOKEN agent-sandbox:latest claude -p "say hello" --dangerously-skip-permissions --output-format json

smoke-gh: build
	docker run --rm -e GH_TOKEN=$$GH_TOKEN agent-sandbox:latest gh auth status

up:
	docker compose up

app:
	uv run src/app.py

worker:
	uv run src/worker.py fake

cli:
	uv run src/worker.py cli "$(PROMPT)" $(if $(REPO),--repo=$(REPO)) $(if $(MODEL_PROVIDER),--model-provider=$(MODEL_PROVIDER))

dev:
	docker compose up -d
	trap 'docker compose down; kill 0' EXIT; \
	uv run src/app.py & \
	uv run src/worker.py slack & \
	wait

logs:
	tail -f logs/app.log logs/worker.log

test:
	python -m pytest tests/ -v

lint:
	pyright
