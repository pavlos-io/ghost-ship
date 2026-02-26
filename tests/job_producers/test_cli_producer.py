from unittest.mock import MagicMock, call

from job_producers.cli import CliJobProducer
from run_managers.interface import RunManagerType


def _make_producer(prompt="say hello", repo=None):
    queue = MagicMock()
    run_manager = MagicMock()
    run_manager.create_run.return_value = "run-abc"
    producer = CliJobProducer(
        queue=queue,
        prompt=prompt,
        run_manager=run_manager,
        run_manager_type=RunManagerType.FAKE,
        repo=repo,
    )
    return producer, queue, run_manager


# ── start() ───────────────────────────────────────────────────────


def test_start_pings_creates_run_and_enqueues():
    producer, queue, run_manager = _make_producer()
    producer.start()

    queue.ping.assert_called_once()
    run_manager.create_run.assert_called_once()
    queue.enqueue.assert_called_once()


def test_start_enqueues_correct_job_fields():
    producer, queue, _ = _make_producer(prompt="fix bug", repo="my-repo")
    producer.start()

    job = queue.enqueue.call_args[0][0]
    assert job["thread_context"] == "fix bug"
    assert job["trigger_user_name"] == "cli-user"
    assert job["repo"] == "my-repo"
    assert job["run_id"] == "run-abc"
    assert job["run_manager_type"] == RunManagerType.FAKE


def test_start_does_not_enqueue_when_create_run_fails():
    producer, queue, run_manager = _make_producer()
    run_manager.create_run.side_effect = RuntimeError("API down")

    producer.start()

    queue.ping.assert_called_once()
    queue.enqueue.assert_not_called()
