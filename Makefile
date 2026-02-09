.PHONY: build smoke smoke-gh up app worker dev logs

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
	uv run src/worker.py

dev:
	docker compose up -d
	trap 'docker compose down; kill 0' EXIT; \
	uv run src/app.py & \
	uv run src/worker.py & \
	wait

logs:
	tail -f logs/app.log logs/worker.log
