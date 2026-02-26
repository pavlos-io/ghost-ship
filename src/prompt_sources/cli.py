import random
import sys
from typing import Iterator

from prompt_sources.interface import Job, ModelProvider
from run_managers.common import RunMetadata
from run_managers.interface import RunManager, RunManagerType


class CliPromptSource:
    def __init__(
        self,
        prompt: str,
        run_manager: RunManager,
        run_manager_type: RunManagerType,
        repo: str | None = None,
        model_provider: ModelProvider = ModelProvider.CLAUDE,
    ):
        self.prompt = prompt
        self.run_manager = run_manager
        self.run_manager_type = run_manager_type
        self.repo = repo
        self.model_provider = model_provider

    def jobs(self) -> Iterator[Job]:
        metadata = RunMetadata(
            trigger_user_name="cli-user",
            source="cli",
            thread_context=self.prompt,
            repo=self.repo,
        )
        run_id = self.run_manager.create_run(metadata)

        yield Job(
            thread_context=self.prompt,
            trigger_user_name="cli-user",
            repo=self.repo,
            run_id=run_id,
            run_manager_type=self.run_manager_type,
            model_provider=self.model_provider,
        )

    def context_block(self, job: Job) -> str:
        return (
            "## CLI prompt\n"
            "The following prompt was provided via the command line:\n\n"
            f"{job['thread_context']}"
        )

    def log_metadata(self, job: Job) -> dict:
        return {
            "source": "cli",
            "trigger_user_name": job["trigger_user_name"],
            "repo": job.get("repo"),
        }

    def session_label(self, job: Job) -> str:
        return f"cli-{random.randint(1000, 9999)}"

    def reply(self, job: Job, text: str) -> None:
        print(text)

    def reply_error(self, job: Job, text: str) -> None:
        print(f"Error: {text}", file=sys.stderr)
