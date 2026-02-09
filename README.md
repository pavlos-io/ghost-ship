# ghost-ship — Slack-Native Agent Sandbox

A proof-of-concept that wires up: **Slack mention → Redis queue → Docker sandbox → result posted back to Slack**.

When mentioned in Slack, the bot queues a job. The worker spins up a Docker sandbox, runs an agent loop (Claude API with tool use), and posts the result back to the thread. The agent can read/edit files, run commands, and search code inside the sandbox.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker Desktop (running)
- A Slack workspace you can install apps to

## Slack App Setup

1. Go to https://api.slack.com/apps → **Create New App** → **From Scratch**.
2. **OAuth & Permissions** — add these bot token scopes:
   - `app_mentions:read`
   - `channels:history`
   - `chat:write`
   - `users:read`
3. **Socket Mode** — enable it → generate an App-Level Token with the `connections:write` scope → copy the token (`xapp-...`).
4. **Event Subscriptions** — enable events → subscribe to the `app_mention` bot event. No request URL is needed with Socket Mode.
5. **Install** the app to your workspace.
6. Copy the **Bot Token** (`xoxb-...`) from the OAuth & Permissions page.

## Running Locally

### 1. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` with your actual tokens.

### 2. Set up Python environment

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Build the sandbox image

```bash
make build
```

Rebuild after any changes to `Dockerfile.sandbox`.

Smoke test the CLI inside the image:

```bash
make smoke
```

### 4. Start everything

```bash
make dev
```

This starts Redis, the Slack listener, and the worker in one command. Ctrl+C stops all of them.

To run each component separately:

```bash
make up       # Redis
make app      # Slack listener
make worker   # Job worker
```

### 7. Test it

**Sandbox-only mode** (no GitHub):

1. Invite your bot to a Slack channel.
2. Mention it: `@agent create a file called hello.py that prints "Hello, world!" and run it`.
3. The bot replies "Got it, working on it..."
4. The worker spins up a Docker sandbox, the agent loop creates the file, runs it, and posts a summary back in the thread.

**GitHub repo mode** (requires `GH_TOKEN` and `GH_OWNER`):

1. Mention the bot with a repo reference: `@agent repo:my-backend fix the login bug`.
2. The worker clones `GH_OWNER/my-backend` into the sandbox, creates a branch, makes changes, and opens a PR.
3. Check the repo for a new branch and pull request.

## Verifying

- **Container cleaned up:** `docker ps` should show no `agent-sandbox` containers after the job completes.
- **Queue drained:** `redis-cli LLEN jobs` should return `0`.

## Logging

Both processes log to the console (INFO+) and to files in `logs/` (DEBUG+):

- `logs/app.log` — Slack events, thread fetching, parsing, Redis enqueue
- `logs/worker.log` — job pickup, container lifecycle, command execution, Slack posting

Tail them in real time:

```bash
make logs
```

## GitHub Integration (optional)

To enable `repo:repo-name` commands that clone repos, create branches, and open PRs:

1. **Create a fine-grained Personal Access Token:**
   - Go to GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens**.
   - Set **Resource owner** to your org/user (`GH_OWNER`).
   - Under **Repository access**, select the repos the agent should work on.
   - Grant these **Repository permissions:**
     - Contents: **Read and write** (clone + push)
     - Pull requests: **Read and write** (create PRs)
     - Metadata: **Read** (required, auto-selected)
   - Set an expiration (required for fine-grained tokens).
   - Copy the token (`github_pat_...`).

2. **Add to `.env`:**
   ```
   GH_TOKEN=github_pat_your-token
   GH_OWNER=your-org-or-username
   ```

3. **Rebuild the sandbox image** (it now includes the `gh` CLI):
   ```bash
   make build
   ```

4. **Smoke test `gh` inside the sandbox:**
   ```bash
   make smoke-gh
   ```

**Alternative: Classic PAT** — generate with scopes `repo` + `read:org`. Simpler but grants broader access than fine-grained tokens.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot user OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes (app.py only) | App-level token for Socket Mode (`xapp-...`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes (worker.py only) | Claude Code OAuth token for authentication (generate with `claude setup-token`) |
| `GH_TOKEN` | No | GitHub Personal Access Token for `repo:` commands (fine-grained PAT with Contents, Pull requests, Metadata permissions) |
| `GH_OWNER` | No | GitHub org or username — combined with `repo:name` to form `GH_OWNER/name` |
| `REDIS_HOST` | No | Redis host, defaults to `localhost` |
