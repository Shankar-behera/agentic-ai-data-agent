import os

# Must run before any `src` import so Settings picks these up.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DB_HOST", "localhost")
# DB_PORT loaded from .env
os.environ.setdefault("DB_NAME", "rides_db")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "0")

import json  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any, Optional

import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from src.core.database import DatabaseUtil  # noqa: E402
from src.llm.provider import LLMProvider  # noqa: E402


class FakeLLM(LLMProvider):
    """Scripted LLM. `rules` maps a substring of the prompt to a reply (or a callable(prompt) -> reply)."""

    def __init__(self, rules: list[tuple[str, Any]]):
        super().__init__(model_name="fake", temperature=0.0, timeout=1)
        self.rules = rules
        self.prompts: list[str] = []

    def _reply(self, prompt: str) -> str:
        self.prompts.append(prompt)
        for needle, reply in self.rules:
            if needle in prompt:
                return reply(prompt) if callable(reply) else reply
        raise RuntimeError(f"FakeLLM has no rule for prompt: {prompt[:80]!r}")

    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> str:
        return self._reply(prompt)

    def generate_structured(self, prompt: str, schema: type[BaseModel], system_prompt: Optional[str] = None, **kwargs: Any) -> Any:
        return schema.model_validate(json.loads(self._reply(prompt)))

    def generate_with_messages(self, messages: Any, **kwargs: Any) -> str:
        return self._reply(str(messages))

    def get_model(self) -> Any:
        return None

    def health_check(self) -> dict[str, Any]:
        return {"reachable": True, "model_available": True}


class FakeDB:
    """Stands in for DatabaseUtil in agent tests."""

    def __init__(self, results: list[Any]):
        self.results = list(results)  # each item: QueryResult or Exception
        self.executed: list[str] = []

    def get_schema_details(self, schema_name: str = "public") -> str:
        return "Table: rides\n  ride_id (integer)\n  fare (numeric)\n  status (text)"

    def execute_readonly(self, query: str, max_rows: Optional[int] = None) -> Any:
        self.executed.append(query)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_llm_factory() -> Callable[[list[tuple[str, Any]]], FakeLLM]:
    return FakeLLM


@pytest.fixture(scope="session")
def live_db() -> DatabaseUtil:
    db = DatabaseUtil(readonly=True)
    if not db.ping():
        pytest.skip("Postgres with the rides_db seed is not reachable")
    return db

