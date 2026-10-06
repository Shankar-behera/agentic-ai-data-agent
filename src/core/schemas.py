from operator import add
from typing import Annotated, Any, Literal, Optional

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


def get_field(state: Any, name: str, default: Any = None) -> Any:
    """Safely read a field from either a dict or a Pydantic model."""
    if isinstance(state, dict):
        return state.get(name, default)
    return getattr(state, name, default)


class AgentState(BaseModel):
    """State of the SQL analyst graph."""

    messages: Annotated[list[BaseMessage], add] = Field(default_factory=list)
    user_question: str = Field(..., description="Original user question")
    curated_question: str = ""
    prompt_query_context: str = Field(default="", description="Schema text given to the LLM")
    generated_sql_query: str = ""
    is_safe: Literal["Yes", "No"] = "No"
    safety_comments: str = ""
    sql_execution_result: str = ""
    execution_error: Optional[str] = Field(default=None, description="Last DB error, fed back for self-correction")
    row_count: int = 0
    final_answer: str = ""
    iteration_count: int = Field(default=0, description="SQL generation attempts so far")
    error: Optional[str] = None


class RouterSchema(BaseModel):
    answer: Literal["sql", "etl"] = Field(..., description="Classification: sql or etl")
    comments: str = Field(default="", description="Additional comments")


class ETLPlan(BaseModel):
    tool: Literal["extract", "transform"]
    url: Optional[str] = None
    output_folder: str = "extract"
    format: str = "csv"
    input_file_path: Optional[str] = None
    output_format: str = "csv"


class ETLAgentState(BaseModel):
    messages: Annotated[list[BaseMessage], add] = Field(default_factory=list)
    user_question: str = ""
    plan: Optional[dict[str, Any]] = None
    execution_result: str = ""
    final_answer: str = ""
    iteration_count: int = 0
    error: Optional[str] = None


class SQLSafetyResult(BaseModel):
    is_safe: Literal["Yes", "No"] = Field(..., description="Whether SQL is safe")
    reason: str = Field(..., description="Reason for safety decision")
    suggested_fix: Optional[str] = None


class DataAgentState(BaseModel):
    messages: Annotated[list[BaseMessage], add] = Field(default_factory=list)
    user_question: str = Field(..., description="Original user question")
    route_response: str = ""
    generated_sql: str = ""
    final_answer: str = ""
    iteration_count: int = 0
    error: Optional[str] = None
