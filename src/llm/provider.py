from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from src.core.config import settings
from src.core.exceptions import ConfigurationError

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
    ):
        self.model_name = model_name or settings.llm_model
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.timeout = timeout or settings.llm_timeout

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> str: ...

    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: Optional[str] = None, **kwargs: Any
    ) -> T: ...

    @abstractmethod
    def generate_with_messages(self, messages: list[dict[str, str]] | list[BaseMessage], **kwargs: Any) -> str: ...

    @abstractmethod
    def get_model(self) -> Any: ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Return {"reachable": bool, "model_available": bool}. Must never raise."""


def create_llm_provider(provider: Optional[str] = None, **kwargs: Any) -> LLMProvider:
    """Build a provider. Construction performs no network I/O."""
    provider_name = provider or settings.llm_provider
    if provider_name == "ollama":
        from src.llm.ollama import OllamaProvider

        return OllamaProvider(**kwargs)
    raise ConfigurationError(f"Unsupported LLM provider: {provider_name}")
