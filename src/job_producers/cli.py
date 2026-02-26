from queues.queue import JobQueue
from prompt_sources.interface import Job, ModelProvider
from run_managers.interface import RunManager, RunManagerType
from run_managers.common import RunMetadata
from log_config import setup_logging

logger = setup_logging("cli_producer")


class CliJobProducer:
    def __init__(
        self,
        queue: JobQueue,
        prompt: str,
        run_manager: RunManager,
        run_manager_type: RunManagerType,
        repo: str | None = None,
        model_provider: ModelProvider = ModelProvider.CLAUDE,
    ):
        self.queue = queue
        self.prompt = prompt
        self.run_manager = run_manager
        self.run_manager_type = run_manager_type
        self.repo = repo
        self.model_provider = model_provider

    def start(self) -> None:
        logger.info("Starting CLI producer")
        self.queue.ping()

        metadata = RunMetadata(
            trigger_user_name="cli-user",
            source="cli",
            thread_context=self.prompt,
            repo=self.repo,
        )
        try:
            run_id = self.run_manager.create_run(metadata)
        except Exception as e:
            logger.error(f"Failed to create run, not enqueuing job: {e}")
            return

        job: Job = {
            "thread_context": self.prompt,
            "trigger_user_name": "cli-user",
            "repo": self.repo,
            "run_id": run_id,
            "run_manager_type": self.run_manager_type,
            "model_provider": self.model_provider,
        }
        self.queue.enqueue(job)
        logger.info("CLI job enqueued")

    def stop(self) -> None:
        pass
