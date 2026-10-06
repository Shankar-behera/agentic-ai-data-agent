import re
from typing import Any, Optional, TypeVar

import httpx
import requests
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_ollama import ChatOllama
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.exceptions import LLMError
from src.core.logging import get_logger
from src.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)
logger = get_logger(__name__)

# Errors worth retrying: the server is busy, restarting, or the connection dropped.
_TRANSIENT = (httpx.TransportError, requests.exceptions.ConnectionError, ConnectionError, TimeoutError)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(model_name, temperature, timeout)
        self.base_url = base_url or settings.ollama_base_url
        self._clients: dict[bool, ChatOllama] = {}

    # ── clients (lazy: constructing the provider never touches the network) ──
    def _client(self, json_mode: bool = False) -> ChatOllama:
        if json_mode not in self._clients:
            self._clients[json_mode] = ChatOllama(
                model=self.model_name,
                temperature=self.temperature,
                base_url=self.base_url,
                num_predict=settings.llm_max_tokens,
                num_ctx=settings.llm_num_ctx,
                format="json" if json_mode else "",
                # ChatOllama has no `timeout` field; this is the supported way to apply one.
                client_kwargs={"timeout": self.timeout},
            )
        return self._clients[json_mode]

    def get_model(self) -> ChatOllama:
        return self._client()

    def health_check(self) -> dict[str, Any]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            response.raise_for_status()
            names = {m.get("name") for m in response.json().get("models", [])}
            wanted = self.model_name
            available = wanted in names or (":" not in wanted and f"{wanted}:latest" in names)
            return {"reachable": True, "model_available": available}
        except Exception:  # noqa: BLE001
            return {"reachable": False, "model_available": False}

    # ── invocation ─────────────────────────────────────────────
    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(settings.max_retries + 1),
        wait=wait_exponential(multiplier=1, max=8),
        reraise=True,
    )
    def _invoke(self, messages: list[BaseMessage], json_mode: bool = False) -> str:
        response = self._client(json_mode).invoke(messages)
        content = response.content
        return content if isinstance(content, str) else str(content)

    @staticmethod
    def _messages(prompt: str, system_prompt: Optional[str] = None) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        return messages

    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> str:
        try:
            return self._invoke(self._messages(prompt, system_prompt))
        except Exception as e:
            logger.error("llm_generation_failed", error=str(e), exc_info=True)
            raise LLMError(f"Ollama generation failed: {e}") from e

    def generate_structured(
        self, prompt: str, schema: type[T], system_prompt: Optional[str] = None, **kwargs: Any
    ) -> T:
        """JSON-mode generation with parse retries (small local models often emit near-JSON)."""
        parser: PydanticOutputParser[T] = PydanticOutputParser(pydantic_object=schema)
        base_prompt = f"{prompt}\n\n{parser.get_format_instructions()}"
        last_error: Exception | None = None
        for attempt in range(settings.max_retries + 1):
            full_prompt = base_prompt
            if last_error is not None:
                full_prompt += "\n\nYour previous reply was not valid JSON for this schema. Reply with JSON only."
            try:
                raw = self._invoke(self._messages(full_prompt, system_prompt), json_mode=True)
                match = _JSON_OBJECT.search(raw)
                return parser.parse(match.group(0) if match else raw)
            except OutputParserException as e:
                last_error = e
                logger.warning("llm_structured_parse_failed", attempt=attempt + 1, error=str(e)[:200])
            except Exception as e:
                logger.error("llm_structured_failed", error=str(e), exc_info=True)
                raise LLMError(f"Structured generation failed: {e}") from e
        raise LLMError(f"Failed to parse structured output: {last_error}")

    def generate_with_messages(self, messages: list[dict[str, str]] | list[BaseMessage], **kwargs: Any) -> str:
        converted: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, dict):
                role, content = msg.get("role"), msg.get("content", "")
                if role == "system":
                    converted.append(SystemMessage(content=content))
                elif role == "assistant":
                    converted.append(AIMessage(content=content))
                else:
                    converted.append(HumanMessage(content=content))
            else:
                converted.append(msg)
        try:
            return self._invoke(converted)
        except Exception as e:
            logger.error("llm_message_generation_failed", error=str(e), exc_info=True)
            raise LLMError(f"Message-based generation failed: {e}") from e
