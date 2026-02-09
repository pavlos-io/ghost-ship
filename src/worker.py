import base64
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

import docker
import redis
from slack_sdk import WebClient

from log_config import setup_logging

logger = setup_logging("worker")

r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=6379, db=0)
slack = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
docker_client = docker.from_env(timeout=700)

SANDBOX_IMAGE = "agent-sandbox:latest"


def _build_system_prompt(thread_context: str, repo: str | None = None) -> str:
    prompt = (
        "You are an autonomous software engineering agent running inside a Docker sandbox.\n"
        "Your workspace is /workspace. All file paths are relative to that directory.\n\n"
        "## Slack thread context\n"
        "The following messages are from the Slack thread that triggered this task:\n\n"
        f"{thread_context}\n\n"
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


def provision_sandbox():
    """Spin up a Docker sandbox container with Claude Code auth."""
    logger.info(f"Provisioning sandbox (image: {SANDBOX_IMAGE})...")
    start = time.time()

    env = {"CLAUDE_CODE_OAUTH_TOKEN": os.environ["CLAUDE_CODE_OAUTH_TOKEN"]}
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


def _run_claude_in_sandbox(container, job: dict) -> str:
    """Run Claude Code CLI inside the sandbox and return the result text."""
    repo = job.get("repo")

    # Clone repo into workspace if specified
    if repo:
        # Configure git to use gh as credential helper (needed for push)
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

    thread_context = job.get("thread_context", "(no context)")
    system_prompt = _build_system_prompt(thread_context, repo=repo)

    # Write system prompt to file inside the container (avoids shell escaping issues)
    encoded = base64.b64encode(system_prompt.encode()).decode()
    container.exec_run(
        ["sh", "-c", f"echo {encoded} | base64 -d > /tmp/system-prompt.txt"],
    )

    user_prompt = (
        "Complete the task described in the Slack thread above. "
        "Use the available tools to explore, create, edit, and run code in the workspace."
    )

    cmd = (
        f"timeout --signal=KILL 600 claude -p {_shell_quote(user_prompt)} "
        f"--output-format json "
        f"--dangerously-skip-permissions " # TODO: maybe give more narrow perms?
        f"--max-turns 50 "
        f"--append-system-prompt-file /tmp/system-prompt.txt"
    )

    logger.info(f"Running Claude Code CLI in {container.short_id}")

    # Debug: check claude binary accessibility
    # dbg_code, dbg_out = container.exec_run(["sh", "-c", "which claude && claude --version && whoami"], demux=True)
    # dbg_stdout = dbg_out[0].decode() if dbg_out[0] else ""
    # dbg_stderr = dbg_out[1].decode() if dbg_out[1] else ""
    # logger.debug(f"Container debug | exit={dbg_code} | stdout: {dbg_stdout.strip()} | stderr: {dbg_stderr.strip()}")

    start = time.time()

    exit_code, output = container.exec_run(
        ["sh", "-c", cmd],
        workdir="/workspace",
        demux=True,
    )

    stdout = output[0].decode() if output[0] else ""
    stderr = output[1].decode() if output[1] else ""
    elapsed = time.time() - start

    logger.info(f"Claude CLI finished | exit_code={exit_code} | took {elapsed:.2f}s")
    if stderr:
        logger.warning(f"STDERR:\n{stderr.rstrip()}")

    # Handle timeout (SIGKILL → exit code 137)
    if exit_code == 137:
        logger.warning("Claude CLI was killed (timeout or OOM)")
        return "Agent timed out after 10 minutes."

    # Parse JSON output
    try:
        result_json = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Claude CLI output as JSON. Raw output:\n{stdout[:2000]}")
        # Fall back to raw text if JSON parsing fails
        return stdout.strip() if stdout.strip() else "Agent produced no output."

    is_error = result_json.get("is_error", False)
    subtype = result_json.get("subtype", "")
    cost = result_json.get("total_cost_usd", 0)
    num_turns = result_json.get("num_turns", 0)

    result_text = result_json.get("result", "")
    logger.info(f"Claude result: is_error={is_error} subtype={subtype} cost=${cost:.4f} turns={num_turns}")
    logger.debug(f"Claude result text ({len(result_text)} chars): {result_text[:500]}")

    if is_error:
        error_text = result_json.get("result", "Agent encountered an error.")
        if subtype == "error_max_turns":
            return f"Agent stopped after reaching the maximum number of turns.\n\n{error_text}"
        return f"Agent error: {error_text}"

    return result_text or "(Agent finished without a summary)"


def _shell_quote(s: str) -> str:
    """Shell-quote a string using single quotes."""
    return "'" + s.replace("'", "'\\''") + "'"


def destroy_sandbox(container):
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


def process_job(job: dict):
    """Process a single job: spin up sandbox, run Claude CLI, post result, teardown."""
    channel = job["channel_id"]
    thread_ts = job["thread_ts"]
    trigger = job.get("trigger_user_name", "someone")

    logger.info(f"--- Processing job ---")
    logger.info(f"Trigger: {trigger} | Channel: {channel} | Thread: {thread_ts}")
    logger.debug(f"Thread context:\n{job.get('thread_context', '(none)')}")

    job_start = time.time()
    container = None
    try:
        container = provision_sandbox()
        result_text = _run_claude_in_sandbox(container, job)

        slack.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=result_text,
        )
        logger.info("Result posted to Slack")

    except Exception as e:
        logger.error(f"Job failed: {e}", exc_info=True)
        try:
            slack.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Something went wrong: {e}",
            )
            logger.info("Error message posted to Slack")
        except Exception as e2:
            logger.error(f"Failed to post error to Slack: {e2}", exc_info=True)

    finally:
        if container:
            destroy_sandbox(container)
        elapsed = time.time() - job_start
        logger.info(f"Job completed in {elapsed:.2f}s")
        logger.info(f"--- Job done ---")


def main():
    logger.info("=" * 60)
    logger.info("Worker starting")
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

    while True:
        _, raw = r.blpop("jobs", timeout=0)
        job = json.loads(raw)
        queue_len = r.llen("jobs")
        logger.info(f"Job received | Remaining in queue: {queue_len}")
        process_job(job)


if __name__ == "__main__":
    main()
