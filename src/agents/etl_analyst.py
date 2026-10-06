import re
from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.core.exceptions import AppError, SecurityError, ToolExecutionError, ValidationError
from src.core.logging import get_logger
from src.core.schemas import ETLAgentState, ETLPlan, get_field
from src.llm.prompts import ETL_ANSWER_PROMPT, ETL_CODE_GENERATE_PROMPT, ETL_PLAN_PROMPT
from src.llm.provider import LLMProvider, create_llm_provider
from src.tools.etl import ETLTools

logger = get_logger(__name__)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _kv(text: str, key: str) -> Optional[str]:
    """Read ``key: "value"`` or ``key="value"`` (the two syntaxes models actually produce)."""
    m = re.search(rf"[\"']?{key}[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE)
    return m.group(1) if m else None


def parse_tool_call(text: str) -> Optional[ETLPlan]:
    """Fallback parser for when JSON mode fails. Returns None if no tool can be identified."""
    low = text.lower()
    tool = _kv(low, "tool")
    if tool not in ("extract", "transform"):
        if "extract_load_tool" in low or "extract" in low.split("(")[0]:
            tool = "extract"
        elif "transform_load_tool" in low or "transform" in low.split("(")[0]:
            tool = "transform"
        else:
            return None
    return ETLPlan(
        tool=tool,
        url=_kv(text, "url"),
        output_folder=_kv(text, "output_folder") or "extract",
        format=(_kv(text, "format") or "csv").lower(),
        input_file_path=_kv(text, "input_file_path"),
        output_format=(_kv(text, "output_format") or "csv").lower(),
    )


def clean_code(raw: str) -> str:
    fenced = _CODE_FENCE.search(raw)
    return (fenced.group(1) if fenced else raw).strip()


class ETLAnalystAgent:
    """plan -> execute -> summarize. One tool call per request; no re-planning loop."""

    def __init__(self, tools: Optional[ETLTools] = None, llm: Optional[LLMProvider] = None):
        self._tools = tools
        self._llm = llm
        self.graph = self._build_graph()

    @property
    def etl_tools(self) -> ETLTools:
        if self._tools is None:
            self._tools = ETLTools()
        return self._tools

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = create_llm_provider(temperature=0.1)
        return self._llm

    def _build_graph(self) -> Any:
        g = StateGraph(ETLAgentState)
        g.add_node("make_plan", self._plan)  # node names must not collide with state keys ("plan")
        g.add_node("execute", self._execute)
        g.add_node("finalize", self._finalize)
        g.add_edge(START, "make_plan")
        g.add_conditional_edges("make_plan", lambda s: "finalize" if s.error else "execute", {"execute": "execute", "finalize": "finalize"})
        g.add_edge("execute", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    # ── nodes ──────────────────────────────────────────────────
    def _plan(self, state: ETLAgentState) -> dict[str, Any]:
        prompt = ETL_PLAN_PROMPT.format(question=state.user_question)
        plan: Optional[ETLPlan] = None
        try:
            plan = self.llm.generate_structured(prompt, ETLPlan)
        except Exception as e:  # noqa: BLE001 - try the tolerant text parser next
            logger.warning("etl_structured_plan_failed", error=str(e)[:200])
            try:
                plan = parse_tool_call(self.llm.generate(prompt))
            except Exception as e2:  # noqa: BLE001
                logger.error("etl_plan_failed", error=str(e2)[:200])
        if plan is None:
            return {"error": "I couldn't work out which ETL operation you want."}
        if plan.tool == "extract" and not plan.url:
            return {"error": "The extract step needs a URL."}
        if plan.tool == "transform" and not plan.input_file_path:
            return {"error": "The transform step needs an input file path."}
        return {"plan": plan.model_dump(), "iteration_count": 1}

    def _execute(self, state: ETLAgentState) -> dict[str, Any]:
        plan = ETLPlan(**(state.plan or {}))
        try:
            if plan.tool == "extract":
                result = self.etl_tools.extract_load(plan.url or "", plan.output_folder, plan.format)
            else:
                result = self._transform(plan, state.user_question)
        except (ValidationError, SecurityError, ToolExecutionError) as e:
            logger.warning("etl_tool_rejected", tool=plan.tool, error=e.message)
            return {"error": e.message}  # these messages are written for the caller
        except AppError as e:
            logger.error("etl_tool_failed", tool=plan.tool, error=e.message, exc_info=True)
            return {"error": "The ETL operation failed."}
        except Exception as e:  # noqa: BLE001
            logger.error("etl_tool_crashed", tool=plan.tool, error=str(e), exc_info=True)
            return {"error": "The ETL operation failed unexpectedly."}
        return {"execution_result": str(result)}

    def _transform(self, plan: ETLPlan, question: str) -> dict[str, Any]:
        context = self.etl_tools.transform_load_context(plan.input_file_path or "")
        code = clean_code(
            self.llm.generate(
                ETL_CODE_GENERATE_PROMPT.format(
                    rows=context["rows"],
                    columns=context["columns"],
                    sample_data=context["sample_data"],
                    question=question,
                )
            )
        )
        context["output_format"] = plan.output_format
        return self.etl_tools.execute_pandas_code(code, context)

    def _finalize(self, state: ETLAgentState) -> dict[str, Any]:
        if state.error:
            return {"final_answer": f"ETL failed: {state.error}"}
        try:
            answer = self.llm.generate(ETL_ANSWER_PROMPT.format(result=state.execution_result)).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("etl_summary_failed", error=str(e)[:200])
            answer = ""
        answer = answer or f"ETL completed: {state.execution_result}"
        return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

    # ── public API ─────────────────────────────────────────────
    def invoke(self, user_question: str) -> dict[str, Any]:
        initial = ETLAgentState(user_question=user_question, messages=[HumanMessage(content=user_question)])
        try:
            final = self.graph.invoke(initial)
        except Exception as e:  # noqa: BLE001
            logger.error("etl_agent_crashed", error=str(e), exc_info=True)
            return {"success": False, "answer": "The ETL agent failed unexpectedly.", "error": "internal_error"}
        error = get_field(final, "error")
        return {"success": error is None, "answer": get_field(final, "final_answer", ""), "error": error}


@lru_cache(maxsize=1)
def get_etl_analyst_agent() -> ETLAnalystAgent:
    return ETLAnalystAgent()
