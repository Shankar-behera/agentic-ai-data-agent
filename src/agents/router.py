from typing import Any, Optional

from src.core.logging import get_logger
from src.core.schemas import RouterSchema
from src.llm.prompts import ROUTER_PROMPT, ROUTER_SYSTEM
from src.llm.provider import LLMProvider, create_llm_provider

logger = get_logger(__name__)

_ETL_HINTS = (
    "extract",
    "download",
    "fetch from",
    "http://",
    "https://",
    "transform",
    "clean the file",
    "convert",
    ".csv",
    ".parquet",
    ".json",
    "upload",
)


def heuristic_route(question: str) -> str:
    q = question.lower()
    return "etl" if any(hint in q for hint in _ETL_HINTS) else "sql"


class RouterAgent:
    """Classifies a question as SQL or ETL; falls back to keyword rules if the LLM misbehaves."""

    def __init__(self, llm: Optional[LLMProvider] = None):
        self._llm = llm

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = create_llm_provider(temperature=0.0)
        return self._llm

    def route(self, question: str) -> dict[str, Any]:
        # Fast-path unambiguous ETL file/URL tasks without waiting 30s for LLM routing
        if heuristic_route(question) == "etl":
            return {"intent": "etl", "comments": "deterministic etl keyword match", "success": True}

        try:
            result = self.llm.generate_structured(
                prompt=ROUTER_PROMPT.format(question=question),
                schema=RouterSchema,
                system_prompt=ROUTER_SYSTEM,
            )
            return {"intent": result.answer, "comments": result.comments, "success": True}
        except Exception as e:  # noqa: BLE001
            intent = heuristic_route(question)
            logger.warning("router_llm_failed_using_heuristic", error=str(e)[:200], intent=intent)
            return {"intent": intent, "comments": "heuristic fallback", "success": False, "error": str(e)}