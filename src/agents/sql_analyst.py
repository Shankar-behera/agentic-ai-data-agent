import re
from functools import lru_cache
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.core.config import settings
from src.core.database import DatabaseUtil
from src.core.logging import get_logger
from src.core.schemas import AgentState, SQLSafetyResult, get_field
from src.llm.prompts import (
    SQL_ANSWER_PROMPT,
    SQL_CURATE_PROMPT,
    SQL_GENERATE_PROMPT,
    SQL_RETRY_SUFFIX,
    SQL_SAFETY_SYSTEM,
    SQL_SYSTEM,
    SQL_VALIDATE_PROMPT,
)
from src.llm.provider import LLMProvider, create_llm_provider
from src.security.sql_validator import SQLValidator

logger = get_logger(__name__)

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_SQL_START = re.compile(
    r"\b(SELECT|WITH|DELETE|DROP|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_INTENT = re.compile(
    r"^\s*(delete|drop|truncate|update|insert|alter|create|grant|revoke)\b",
    re.IGNORECASE,
)


def extract_sql(text: str) -> str:
    """Pull the query out of an LLM reply (fenced block, or prose followed by SQL)."""
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = _SQL_START.search(text)
    if start:
        text = text[start.start():]
    if ";" in text:
        text = text.split(";", 1)[0]
    return text.strip()


class SQLAnalystAgent:
    def __init__(
        self,
        db: Optional[DatabaseUtil] = None,
        llm: Optional[LLMProvider] = None,
        validator: Optional[SQLValidator] = None,
    ):
        self.db_util = db or DatabaseUtil(readonly=True)
        self.sql_validator = validator or SQLValidator()
        self._llm = llm
        self.graph = self._build_graph()

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = create_llm_provider(temperature=0.0)
        return self._llm

    def _build_graph(self) -> Any:
        g = StateGraph(AgentState)
        g.add_node("curate_question", self._curate_question)
        g.add_node("get_schema", self._get_schema)
        g.add_node("generate_sql", self._generate_sql)
        g.add_node("validate_sql", self._validate_sql)
        g.add_node("execute_sql", self._execute_sql)
        g.add_node("cancel_sql", self._cancel_sql)
        g.add_node("finalize", self._finalize)

        g.add_edge(START, "curate_question")
        g.add_conditional_edges(
            "curate_question",
            self._continue_or_finalize,
            {"continue": "get_schema", "finalize": "finalize"},
        )
        g.add_conditional_edges("get_schema", self._continue_or_finalize, {"continue": "generate_sql", "finalize": "finalize"})
        g.add_conditional_edges("generate_sql", self._continue_or_finalize, {"continue": "validate_sql", "finalize": "finalize"})
        g.add_conditional_edges("validate_sql", self._route_after_validation, {"execute": "execute_sql", "cancel": "cancel_sql"})
        g.add_conditional_edges("execute_sql", self._route_after_execution, {"retry": "generate_sql", "finalize": "finalize"})
        g.add_edge("cancel_sql", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def _curate_question(self, state: AgentState) -> Dict[str, Any]:
        original = state.user_question.strip()
        m = _DESTRUCTIVE_INTENT.search(original)
        if m:
            verb = m.group(1).upper()
            logger.warning("destructive_intent_blocked", verb=verb, question=original[:200])
            return {
                "is_safe": "No",
                "safety_comments": f"Query contains forbidden keyword: {verb}",
                "error": "Generated SQL was rejected by safety validation",
                "final_answer": (
                    f"I cannot execute `{verb}` or any data-modifying operation. "
                    "This query failed safety validation because this agent has strictly read-only access to the database."
                ),
            }

        if not settings.sql_curate_question:
            return {"curated_question": original}
        try:
            raw = self.llm.generate(SQL_CURATE_PROMPT.format(question=original)).strip()
            curated = raw.splitlines()[0].strip() if raw else ""
            if not curated or len(curated) > 2 * len(original) + 200:
                curated = original
        except Exception as e:  # noqa: BLE001
            logger.warning("curate_failed", error=str(e)[:200])
            curated = original
        return {"curated_question": curated}

    def _get_schema(self, state: AgentState) -> dict[str, Any]:
        try:
            return {"prompt_query_context": self.db_util.get_schema_details("public")}
        except Exception as e:  # noqa: BLE001
            logger.error("schema_retrieval_failed", error=str(e), exc_info=True)
            return {"error": "Could not read the database schema."}

    def _generate_sql(self, state: AgentState) -> dict[str, Any]:
        attempt = state.iteration_count + 1
        prompt = SQL_GENERATE_PROMPT.format(schema=state.prompt_query_context, question=state.curated_question)
        if state.execution_error:
            prompt += SQL_RETRY_SUFFIX.format(sql=state.generated_sql_query, error=state.execution_error[:500])
        try:
            sql_text = extract_sql(self.llm.generate(prompt, system_prompt=SQL_SYSTEM))
        except Exception as e:  # noqa: BLE001
            logger.error("sql_generation_failed", error=str(e), exc_info=True)
            return {"error": "The language model failed to generate a query.", "iteration_count": attempt}
        logger.info("sql_generated", attempt=attempt, sql=sql_text[:200])
        return {"generated_sql_query": sql_text, "iteration_count": attempt, "execution_error": None}

    def _validate_sql(self, state: AgentState) -> dict[str, Any]:
        ok, reason = self.sql_validator.validate(state.generated_sql_query)
        if not ok:
            logger.warning("sql_rejected", reason=reason, sql=state.generated_sql_query[:200])
            return {"is_safe": "No", "safety_comments": reason}

        update: dict[str, Any] = {
            "is_safe": "Yes",
            "safety_comments": reason,
            "generated_sql_query": self.sql_validator.normalize(state.generated_sql_query),
        }
        if settings.llm_safety_check:
            try:
                verdict = self.llm.generate_structured(
                    prompt=SQL_VALIDATE_PROMPT.format(sql=state.generated_sql_query),
                    schema=SQLSafetyResult,
                    system_prompt=SQL_SAFETY_SYSTEM,
                )
                if verdict.is_safe != "Yes":
                    update.update({"is_safe": "No", "safety_comments": verdict.reason})
            except Exception as e:  # noqa: BLE001
                logger.warning("llm_safety_check_failed", error=str(e)[:200])
        return update

    def _execute_sql(self, state: AgentState) -> dict[str, Any]:
        try:
            result = self.db_util.execute_readonly(state.generated_sql_query)
        except Exception as e:  # noqa: BLE001
            message = (getattr(e, "pgerror", None) or str(e)).strip()
            logger.warning("sql_execution_failed", attempt=state.iteration_count, error=message[:300])
            return {"execution_error": message, "sql_execution_result": ""}
        logger.info("sql_executed", rows=len(result.rows), ms=round(result.elapsed_ms, 1))
        return {
            "sql_execution_result": result.to_text(),
            "row_count": len(result.rows),
            "execution_error": None,
        }

    def _cancel_sql(self, state: AgentState) -> dict[str, Any]:
        return {
            "error": "Generated SQL was rejected by safety validation",
            "final_answer": (
                "I could not run the query that was generated because it failed safety validation "
                f"({state.safety_comments}). Please rephrase your question."
            ),
        }

    def _finalize(self, state: AgentState) -> dict[str, Any]:
        if state.final_answer:
            return {}
        if state.error:
            return {"final_answer": f"Sorry, I couldn't answer that: {state.error}"}
        if state.execution_error:
            detail = "" if settings.is_production else f" Last database error: {state.execution_error[:200]}"
            return {
                "error": "SQL execution failed",
                "final_answer": f"I couldn't produce a working query after {state.iteration_count} attempt(s).{detail}",
            }
        if state.row_count == 0:
            return {"final_answer": "The query ran successfully but returned no matching rows."}
        try:
            answer = self.llm.generate(
                SQL_ANSWER_PROMPT.format(result=state.sql_execution_result, question=state.user_question)
            ).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("answer_generation_failed", error=str(e)[:200])
            answer = ""
        if not answer:
            answer = "Here is the raw result:\n" + state.sql_execution_result
        return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

    @staticmethod
    def _continue_or_finalize(state: AgentState) -> str:
        return "finalize" if state.error else "continue"

    @staticmethod
    def _route_after_validation(state: AgentState) -> str:
        return "execute" if state.is_safe == "Yes" else "cancel"

    @staticmethod
    def _route_after_execution(state: AgentState) -> str:
        if state.execution_error and state.iteration_count <= settings.max_retries:
            return "retry"
        return "finalize"

    def invoke(self, user_question: str) -> dict[str, Any]:
        initial = AgentState(user_question=user_question, messages=[HumanMessage(content=user_question)])
        try:
            final = self.graph.invoke(initial)
        except Exception as e:  # noqa: BLE001
            logger.error("sql_agent_crashed", error=str(e), exc_info=True)
            return {"success": False, "answer": "The SQL agent failed unexpectedly.", "sql": "", "error": "internal_error"}
        error = get_field(final, "error")
        return {
            "success": error is None,
            "answer": get_field(final, "final_answer", ""),
            "sql": get_field(final, "generated_sql_query", ""),
            "result": get_field(final, "sql_execution_result", ""),
            "is_safe": get_field(final, "is_safe", "No"),
            "attempts": get_field(final, "iteration_count", 0),
            "error": error,
        }


@lru_cache(maxsize=1)
def get_sql_analyst_agent() -> SQLAnalystAgent:
    return SQLAnalystAgent()

