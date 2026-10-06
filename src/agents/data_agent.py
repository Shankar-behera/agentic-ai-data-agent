from functools import lru_cache
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.agents.etl_analyst import ETLAnalystAgent, get_etl_analyst_agent
from src.agents.router import RouterAgent
from src.agents.sql_analyst import SQLAnalystAgent, get_sql_analyst_agent
from src.core.logging import get_logger
from src.core.schemas import DataAgentState, get_field

logger = get_logger(__name__)


class DataAgent:
    """Top-level graph: route the question, then hand it to the SQL or ETL agent.

    Sub-agents are injectable (tests) and otherwise built lazily on first use, so
    constructing a DataAgent never needs Ollama or Postgres to be reachable.
    """

    def __init__(
        self,
        router: Optional[RouterAgent] = None,
        sql_agent: Optional[SQLAnalystAgent] = None,
        etl_agent: Optional[ETLAnalystAgent] = None,
    ):
        self.router = router or RouterAgent()
        self._sql_agent = sql_agent
        self._etl_agent = etl_agent
        self.graph = self._build_graph()

    @property
    def sql_agent(self) -> SQLAnalystAgent:
        return self._sql_agent or get_sql_analyst_agent()

    @property
    def etl_agent(self) -> ETLAnalystAgent:
        return self._etl_agent or get_etl_analyst_agent()

    def _build_graph(self) -> Any:
        g = StateGraph(DataAgentState)
        g.add_node("router", self._router_node)
        g.add_node("sql_agent", self._sql_node)
        g.add_node("etl_agent", self._etl_node)
        g.add_edge(START, "router")
        g.add_conditional_edges(
            "router",
            lambda s: s.route_response if s.route_response in ("sql", "etl") else "sql",
            {"sql": "sql_agent", "etl": "etl_agent"},
        )
        g.add_edge("sql_agent", END)
        g.add_edge("etl_agent", END)
        return g.compile()

    def _router_node(self, state: DataAgentState) -> dict[str, Any]:
        result = self.router.route(state.user_question)  # never raises; falls back to keyword rules
        logger.info("query_routed", intent=result["intent"], llm_ok=result.get("success", False))
        return {"route_response": result["intent"]}

    def _sql_node(self, state: DataAgentState) -> dict[str, Any]:
        try:
            result = self.sql_agent.invoke(state.user_question)
        except Exception as e:  # noqa: BLE001
            logger.error("sql_agent_failed", error=str(e), exc_info=True)
            return {"error": "internal_error", "final_answer": "The SQL agent failed unexpectedly."}
        return {
            "final_answer": result.get("answer", ""),
            "generated_sql": result.get("sql", ""),
            "error": result.get("error") if not result.get("success") else None,
            "messages": [AIMessage(content=result.get("answer", ""))],
        }

    def _etl_node(self, state: DataAgentState) -> dict[str, Any]:
        try:
            result = self.etl_agent.invoke(state.user_question)
        except Exception as e:  # noqa: BLE001
            logger.error("etl_agent_failed", error=str(e), exc_info=True)
            return {"error": "internal_error", "final_answer": "The ETL agent failed unexpectedly."}
        return {
            "final_answer": result.get("answer", ""),
            "error": result.get("error") if not result.get("success") else None,
            "messages": [AIMessage(content=result.get("answer", ""))],
        }

    def invoke(self, user_question: str) -> dict[str, Any]:
        initial = DataAgentState(user_question=user_question, messages=[HumanMessage(content=user_question)])
        try:
            final = self.graph.invoke(initial)
        except Exception as e:  # noqa: BLE001
            logger.error("data_agent_failed", error=str(e), exc_info=True)
            return {"success": False, "answer": "The data agent failed unexpectedly.", "route": "unknown",
                    "sql": None, "error": "internal_error"}
        error = get_field(final, "error")
        return {
            "success": error is None,
            "answer": get_field(final, "final_answer", ""),
            "route": get_field(final, "route_response", "") or "unknown",
            "sql": get_field(final, "generated_sql", "") or None,
            "error": error,
        }


@lru_cache(maxsize=1)
def get_data_agent() -> DataAgent:
    return DataAgent()
