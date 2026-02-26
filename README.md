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
make worker cli "prompt"   # Job worker
```

### CLI Mode (no Redis/Slack required)

Run a single prompt directly from the command line. Only requires Docker and `CLAUDE_CODE_OAUTH_TOKEN`.

```bash
# Simple prompt
uv run src/worker.py cli "say hello"

# With a GitHub repo
uv run src/worker.py cli "fix the bug" --repo my-repo

# Via Makefile
make cli PROMPT="say hello"
make cli PROMPT="fix the bug" REPO=my-repo
```

### 5. Test it

**Sandbox-only mode** (no GitHub):

1. Invite your bot to a Slack channel.
2. Mention it: `@agent create a file called hello.py that prints "Hello, world!" and run it`.
3. The bot replies "Got it, working on it..."
4. The worker spins up a Docker sandbox, the agent loop creates the file, runs it, and posts a summary back in the thread.

**GitHub repo mode** (requires `GH_TOKEN` and `GH_OWNER`):

1. Mention the bot with a repo reference: `@agent repo:my-backend fix the login bug`.
2. The worker clones `GH_OWNER/my-backend` into the sandbox, creates a branch, makes changes, and opens a PR.
3. Check the repo for a new branch and pull request.

## Architecture

- **app.py** — Slack listener entry point. Starts job producers.
- **worker.py** — Job processor with two modes: `slack` (pulls from Redis) and `cli` (single prompt). Provisions a Docker sandbox, runs Claude Code CLI inside it, and returns the result.
- **Job Producers** (`job_producers/`) — `SlackJobProducer` listens for `@mentions`, parses threads, enriches context, and enqueues jobs to Redis.
- **Prompt Sources** (`prompt_sources/`) — Abstraction for where jobs come from and how results are delivered. `SlackPromptSource` reads from Redis and replies to Slack. `CliPromptSource` takes a CLI argument and prints to stdout.
- **Context Providers** (`context_providers/`) — Auto-detect external references (Sentry/Jira URLs) in Slack threads and fetch details to include in the prompt. Registered via env vars.
- **Queues** (`queues/`) — Thin Redis wrapper for job enqueue/dequeue.
- **Session Loggers** (`session_loggers/`) — Saves Claude session events as NDJSON files to `logs/sessions/`.

## Tests

```bash
make test
```

## Verifying

- **Container cleaned up:** `docker ps` should show no `agent-sandbox` containers after the job completes.
- **Queue drained:** `redis-cli LLEN jobs` should return `0`.

## Logging

Both processes log to the console (INFO+) and to files in `logs/` (DEBUG+):

- `logs/app.log` — Slack events, thread fetching, parsing, Redis enqueue
- `logs/worker.log` — job pickup, container lifecycle, command execution, Slack posting
- `logs/sessions/*.jsonl` — full Claude session logs (every tool call, message, and result as NDJSON). Each file starts with a `_metadata` line containing job context, followed by one JSON event per line from the `stream-json` output.

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

## Sentry Integration (optional)

To enrich Claude's context with Sentry error details when someone pastes a Sentry issue URL in the Slack thread:

1. **Create a Sentry Auth Token:**
   - Go to Sentry → Settings → Auth Tokens → **Create New Token**.
   - Grant the `event:read`, `issue:read` scopes.
   - Copy the token.

2. **Add to `.env`:**
   ```
   SENTRY_AUTH_TOKEN=your-sentry-auth-token
   # Optional: override the base URL for self-hosted Sentry
   # SENTRY_BASE_URL=https://sentry.io/api/0/
   ```

3. **Usage:**
   - Paste a Sentry issue URL (e.g. `https://my-org.sentry.io/issues/12345/`) in a Slack thread.
   - Mention the bot in that thread.
   - The bot will automatically fetch the issue title, status, stacktrace, breadcrumbs, and request data, and include them in the prompt to Claude.
   - Check `logs/app.log` for "Context enriched" to verify it worked.

## Jira Integration (optional)

To enrich Claude's context with Jira issue details when someone pastes a Jira issue URL in the Slack thread:

1. **Create a Jira API Token:**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens → **Create API token**.
   - Give it a label (e.g. "ghost-ship bot") and copy the token.

2. **Add to `.env`:**
   ```
   JIRA_BASE_URL=https://your-org.atlassian.net
   JIRA_EMAIL=your-email@example.com
   JIRA_API_TOKEN=your-jira-api-token
   ```

3. **Usage:**
   - Paste a Jira issue URL (e.g. `https://your-org.atlassian.net/browse/PROJ-123`) in a Slack thread.
   - Mention the bot in that thread.
   - The bot will automatically fetch the issue summary, status, description, and comments, and include them in the prompt to Claude.
   - Check `logs/app.log` for "Context enriched" to verify it worked.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot user OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes (app.py only) | App-level token for Socket Mode (`xapp-...`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes (worker.py only) | Claude Code OAuth token for authentication (generate with `claude setup-token`) |
| `GH_TOKEN` | No | GitHub Personal Access Token for `repo:` commands (fine-grained PAT with Contents, Pull requests, Metadata permissions) |
| `GH_OWNER` | No | GitHub org or username — combined with `repo:name` to form `GH_OWNER/name` |
| `SENTRY_AUTH_TOKEN` | No | Sentry auth token for fetching issue details from Sentry URLs in threads |
| `SENTRY_BASE_URL` | No | Sentry API base URL, defaults to `https://sentry.io/api/0/` (override for self-hosted) |
| `JIRA_BASE_URL` | No | Jira instance URL (e.g. `https://your-org.atlassian.net`) — all three `JIRA_*` vars must be set to enable |
| `JIRA_EMAIL` | No | Email address of the Jira account used for API access |
| `JIRA_API_TOKEN` | No | Jira API token (create at https://id.atlassian.com/manage-profile/security/api-tokens) |
| `REDIS_HOST` | No | Redis host, defaults to `localhost` |
