from prompt_sources.cli import CliPromptSource
from run_managers.fake import FakeRunManager
from run_managers.interface import RunManagerType


def _make_source(prompt="test", repo=None):
    return CliPromptSource(
        prompt=prompt,
        run_manager=FakeRunManager(),
        run_manager_type=RunManagerType.FAKE,
        repo=repo,
    )


# ── jobs() ────────────────────────────────────────────────────────


def test_jobs_yields_single_job():
    source = _make_source(prompt="say hello")
    jobs = list(source.jobs())
    assert len(jobs) == 1
    assert jobs[0]["thread_context"] == "say hello"
    assert jobs[0]["trigger_user_name"] == "cli-user"
    assert jobs[0]["repo"] is None


def test_jobs_with_repo():
    source = _make_source(prompt="fix bug", repo="my-repo")
    jobs = list(source.jobs())
    assert jobs[0]["repo"] == "my-repo"


def test_jobs_includes_run_id():
    source = _make_source(prompt="do work")
    jobs = list(source.jobs())
    assert jobs[0]["run_id"]  # non-empty string from FakeRunManager


# ── context_block() ──────────────────────────────────────────────


def test_context_block_contains_prompt():
    source = _make_source(prompt="do something")
    job = list(source.jobs())[0]
    block = source.context_block(job)
    assert "do something" in block
    assert "CLI prompt" in block


# ── log_metadata() ───────────────────────────────────────────────


def test_log_metadata_fields():
    source = _make_source(prompt="test", repo="my-repo")
    job = list(source.jobs())[0]
    meta = source.log_metadata(job)
    assert meta["source"] == "cli"
    assert meta["trigger_user_name"] == "cli-user"
    assert meta["repo"] == "my-repo"


# ── session_label() ──────────────────────────────────────────────


def test_session_label_format():
    source = _make_source()
    job = list(source.jobs())[0]
    label = source.session_label(job)
    assert label.startswith("cli-")
    number = int(label.removeprefix("cli-"))
    assert 1000 <= number <= 9999


# ── reply() / reply_error() ──────────────────────────────────────


def test_reply_prints_to_stdout(capsys):
    source = _make_source()
    job = list(source.jobs())[0]
    source.reply(job, "The answer is 42")
    captured = capsys.readouterr()
    assert "The answer is 42" in captured.out


def test_reply_error_prints_to_stderr(capsys):
    source = _make_source()
    job = list(source.jobs())[0]
    source.reply_error(job, "something broke")
    captured = capsys.readouterr()
    assert "Error: something broke" in captured.err
