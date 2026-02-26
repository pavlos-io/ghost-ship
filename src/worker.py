import base64
import json
import os
import time
from collections import Counter
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import docker
import typer
from docker.models.containers import Container

from log_config import setup_logging
from prompt_sources.interface import J, Job, ModelProvider, PromptSource
from run_managers.interface import RunManagerType, build_run_manager
from session_loggers.file_logger import FileSessionLogger

logger = setup_logging("worker")
session_logger = FileSessionLogger()

docker_client = docker.from_env(timeout=700)

SANDBOX_IMAGE = "agent-sandbox:latest"


def _build_system_prompt(context_block: str, repo: str | None = None) -> str:
    prompt = (
        "You are an autonomous software engineering agent running inside a Docker sandbox.\n"
        "Your workspace is /workspace. All file paths are relative to that directory.\n\n"
        f"{context_block}\n\n"
        "## Guidelines\n"
        "- Explore the workspace before making changes (list files, read code).\n"
        "- After editing files, verify your changes (read the file back, run tests if applicable).\n"
    )

    if repo:
        gh_owner = os.environ.get("GH_OWNER", "")
        full_repo = f"{gh_owner}/{repo}" if gh_owner else repo
        prompt += (
            "- When you are done, provide a concise summary of what you did.\n\n"
            "## Git workflow\n"
            f"A GitHub repository ({full_repo}) has been cloned to /workspace.\n"
            "- Create a new branch with a descriptive name for your changes.\n"
            "- Make your changes, verify them (run tests if applicable).\n"
            "- Commit with clear messages.\n"
            "- Push the branch and create a pull request using `gh pr create`.\n"
            "- Include a clear PR title and description of what you changed and why.\n"
        )
    else:
        prompt += (
            "- Do NOT attempt to access the internet or external services.\n"
            "- When you are done, provide a concise summary of what you did.\n"
        )

    return prompt


def provision_sandbox(model_provider: ModelProvider) -> Container:
    """Spin up a Docker sandbox container with auth env vars for the chosen provider."""
    logger.info(f"Provisioning sandbox (image: {SANDBOX_IMAGE}, provider: {model_provider})...")
    start = time.time()

    env: dict[str, str] = {}

    if model_provider == ModelProvider.CLAUDE:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    elif model_provider == ModelProvider.CODEX:
        env["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]

    gh_token = os.environ.get("GH_TOKEN")
    if gh_token:
        env["GH_TOKEN"] = gh_token

    container = docker_client.containers.run(
        image=SANDBOX_IMAGE,
        command="sleep infinity",
        mem_limit="512m",
        cpu_period=100000,
        cpu_quota=100000,  # 1 CPU
        detach=True,
        labels={"role": "agent-sandbox"},
        environment=env,
    )

    elapsed = time.time() - start
    logger.info(f"Container started | ID: {container.short_id} | Name: {container.name} | took {elapsed:.2f}s")
    logger.debug(f"Container details: image={SANDBOX_IMAGE} mem_limit=512m cpu_quota=1")
    return container


def _parse_stream_json(raw_output: str) -> list[dict]:
    """Parse NDJSON (stream-json) output into a list of event dicts."""
    events = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning(f"Skipping malformed NDJSON line: {line[:200]}")
    return events


def _write_system_prompt(container: Container, model_provider: ModelProvider, system_prompt: str) -> None:
    """Write the system prompt into the container at the provider-appropriate location."""
    encoded = base64.b64encode(system_prompt.encode()).decode()

    if model_provider == ModelProvider.CLAUDE:
        container.exec_run(
            ["sh", "-c", f"echo {encoded} | base64 -d > /tmp/system-prompt.txt"],
        )
    elif model_provider == ModelProvider.CODEX:
        # Codex automatically reads AGENTS.md from the workspace root
        container.exec_run(
            ["sh", "-c", f"echo {encoded} | base64 -d > /workspace/AGENTS.md"],
        )


def _build_cli_command(model_provider: ModelProvider, user_prompt: str) -> str:
    """Build the CLI invocation string for the chosen provider."""
    quoted_prompt = _shell_quote(user_prompt)

    if model_provider == ModelProvider.CLAUDE:
        return (
            f"timeout --signal=KILL 600 claude -p {quoted_prompt} "
            f"--verbose --output-format stream-json "
            f"--dangerously-skip-permissions "
            f"--max-turns 50 "
            f"--append-system-prompt-file /tmp/system-prompt.txt"
        )
    elif model_provider == ModelProvider.CODEX:
        return (
            f"timeout --signal=KILL 600 codex exec --json "
            f"--dangerously-bypass-approvals-and-sandbox "
            f"{quoted_prompt}"
        )

    raise ValueError(f"Unknown model provider: {model_provider}")


def _extract_claude_result(events: list[dict]) -> str:
    """Extract the final result text from Claude stream-json events."""
    type_counts = Counter(e.get("type", "unknown") for e in events)
    logger.info(f"Session events: {dict(type_counts)}")

    result_event = None
    for event in reversed(events):
        if event.get("type") == "result":
            result_event = event
            break

    if result_event is None:
        logger.error("No result event found in stream-json output")
        return "Agent produced no output."

    is_error = result_event.get("is_error", False)
    subtype = result_event.get("subtype", "")
    cost = result_event.get("total_cost_usd", 0)
    num_turns = result_event.get("num_turns", 0)
    result_text = result_event.get("result", "")

    logger.info(f"Claude result: is_error={is_error} subtype={subtype} cost=${cost:.4f} turns={num_turns}")
    logger.debug(f"Claude result text ({len(result_text)} chars): {result_text[:500]}")

    if is_error:
        error_text = result_text or "Agent encountered an error."
        if subtype == "error_max_turns":
            return f"Agent stopped after reaching the maximum number of turns.\n\n{error_text}"
        return f"Agent error: {error_text}"

    return result_text or "(Agent finished without a summary)"


def _extract_codex_result(events: list[dict]) -> str:
    """Extract the final result text from Codex NDJSON events."""
    type_counts = Counter(e.get("type", "unknown") for e in events)
    logger.info(f"Session events: {dict(type_counts)}")

    # Collect text from agent_message items in item.completed events
    text_parts: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for event in events:
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                # Codex puts text directly on the item, not nested under content[]
                if item.get("text"):
                    text_parts.append(item["text"])
        elif event.get("type") == "turn.completed":
            usage = event.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

    logger.info(f"Codex usage: input_tokens={total_input_tokens} output_tokens={total_output_tokens}")

    if not text_parts:
        logger.error("No agent_message content found in Codex output")
        return "Agent produced no output."

    result_text = "\n".join(text_parts)
    logger.debug(f"Codex result text ({len(result_text)} chars): {result_text[:500]}")
    return result_text


def _extract_result(events: list[dict], model_provider: ModelProvider) -> str:
    """Dispatch result extraction to the appropriate provider handler."""
    if model_provider == ModelProvider.CLAUDE:
        return _extract_claude_result(events)
    elif model_provider == ModelProvider.CODEX:
        return _extract_codex_result(events)
    raise ValueError(f"Unknown model provider: {model_provider}")


def _run_in_sandbox(container: Container, job: J, source: PromptSource[J], model_provider: ModelProvider) -> str:
    """Run the chosen CLI tool inside the sandbox and return the result text."""
    repo = job.get("repo")

    # Clone repo into workspace if specified
    if repo:
        container.exec_run(["sh", "-c", "gh auth setup-git"], demux=True)

        gh_owner = os.environ["GH_OWNER"]
        full_repo = f"{gh_owner}/{repo}"
        clone_cmd = f"gh repo clone {_shell_quote(full_repo)} /workspace -- --depth=1"
        logger.info(f"Cloning repo {full_repo} into sandbox...")
        exit_code, output = container.exec_run(["sh", "-c", clone_cmd], demux=True)
        clone_stderr = output[1].decode() if output[1] else ""
        if exit_code != 0:
            logger.error(f"Failed to clone repo {full_repo}: {clone_stderr}")
            raise RuntimeError(f"Failed to clone repo {full_repo}: {clone_stderr}")
        logger.info(f"Repo {full_repo} cloned successfully")

    # Authenticate Codex CLI using the API key injected into the container
    if model_provider == ModelProvider.CODEX:
        logger.info("Logging in to Codex CLI...")
        exit_code, output = container.exec_run(
            ["sh", "-c", "printenv OPENAI_API_KEY | codex login --with-api-key"],
            demux=True,
        )
        if exit_code != 0:
            stderr = output[1].decode() if output[1] else ""
            raise RuntimeError(f"Codex login failed: {stderr}")
        logger.info("Codex CLI login successful")

    context_block = source.context_block(job)
    system_prompt = _build_system_prompt(context_block, repo=repo)

    _write_system_prompt(container, model_provider, system_prompt)

    user_prompt = (
        "Complete the task described in the context above. "
        "Use the available tools to explore, create, edit, and run code in the workspace."
    )

    cmd = _build_cli_command(model_provider, user_prompt)

    logger.info(f"Running {model_provider} CLI in {container.short_id}")

    start = time.time()

    exit_code, output = container.exec_run(
        ["sh", "-c", cmd],
        workdir="/workspace",
        demux=True,
    )

    stdout = output[0].decode() if output[0] else ""
    stderr = output[1].decode() if output[1] else ""
    elapsed = time.time() - start

    logger.info(f"{model_provider} CLI finished | exit_code={exit_code} | took {elapsed:.2f}s")
    if stderr:
        logger.warning(f"STDERR:\n{stderr.rstrip()}")

    # Parse NDJSON events (both providers output NDJSON)
    events = _parse_stream_json(stdout)

    # Send events to run tracker
    run_manager = build_run_manager(RunManagerType(job["run_manager_type"]))
    run_manager.send_events(job["run_id"], events)

    # Save session log (even on timeout — partial logs are useful)
    metadata = {
        **source.log_metadata(job),
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "model_provider": str(model_provider),
    }
    label = source.session_label(job)
    session_logger.save(events, metadata, label)

    # Handle timeout (SIGKILL → exit code 137)
    if exit_code == 137:
        logger.warning(f"{model_provider} CLI was killed (timeout or OOM)")
        return "Agent timed out after 10 minutes."

    return _extract_result(events, model_provider)


def _shell_quote(s: str) -> str:
    """Shell-quote a string using single quotes."""
    return "'" + s.replace("'", "'\\''") + "'"


def destroy_sandbox(container: Container) -> None:
    """Stop and remove the sandbox container."""
    logger.info(f"Destroying container {container.short_id}...")
    start = time.time()
    try:
        container.stop(timeout=5)
        container.remove()
        elapsed = time.time() - start
        logger.info(f"Container {container.short_id} destroyed | took {elapsed:.2f}s")
    except Exception as e:
        logger.error(f"Failed to destroy container {container.short_id}: {e}", exc_info=True)


def process_job(job: J, source: PromptSource[J]) -> None:
    """Process a single job: spin up sandbox, run CLI, post result, teardown."""
    trigger = job.get("trigger_user_name", "someone")
    model_provider = ModelProvider(job.get("model_provider", ModelProvider.CLAUDE))

    logger.info(f"--- Processing job ---")
    logger.info(f"Trigger: {trigger} | Provider: {model_provider}")
    logger.debug(f"Thread context:\n{job.get('thread_context', '(none)')}")

    job_start = time.time()
    container = None
    try:
        container = provision_sandbox(model_provider)
        result_text = _run_in_sandbox(container, job, source, model_provider)
        source.reply(job, result_text)

    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        source.reply_error(job, str(e))

    finally:
        if container:
            destroy_sandbox(container)
        elapsed = time.time() - job_start
        logger.info(f"Job completed in {elapsed:.2f}s")
        logger.info(f"--- Job done ---")


app = typer.Typer()


@app.command()
def slack():
    """Run worker in Slack mode (default, existing behavior)."""
    import redis
    from slack_sdk import WebClient

    from prompt_sources.slack import SlackPromptSource

    r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, db=0)
    slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    source = SlackPromptSource(r, slack_client)

    logger.info("=" * 60)
    logger.info("Worker starting (Slack mode)")
    logger.info(f"Redis: {os.environ.get('REDIS_HOST', 'localhost')}:6379")
    logger.info(f"Sandbox image: {SANDBOX_IMAGE}")
    logger.info("=" * 60)

    try:
        r.ping()
        logger.info("Redis connection OK")
    except redis.ConnectionError as e:
        logger.error(f"Cannot connect to Redis: {e}")
        raise

    try:
        docker_client.ping()
        logger.info("Docker connection OK")
    except Exception as e:
        logger.error(f"Cannot connect to Docker: {e}")
        raise

    queue_len = r.llen("jobs")
    logger.info(f"Current queue length: {queue_len}")
    logger.info("Waiting for jobs...")

    for job in source.jobs():
        process_job(job, source)


@app.command()
def cli(prompt: str, repo: Optional[str] = None, model_provider: ModelProvider = ModelProvider.CLAUDE):
    """Run a single prompt from the command line."""
    from prompt_sources.cli import CliPromptSource

    logger.info("=" * 60)
    logger.info(f"Worker starting (CLI mode, provider: {model_provider})")
    logger.info(f"Sandbox image: {SANDBOX_IMAGE}")
    logger.info("=" * 60)

    run_manager = build_run_manager(RunManagerType.WEB)
    source = CliPromptSource(
        prompt=prompt,
        run_manager=run_manager,
        run_manager_type=RunManagerType.WEB,
        repo=repo,
        model_provider=model_provider,
    )
    for job in source.jobs():
        process_job(job, source)


if __name__ == "__main__":
    app()
