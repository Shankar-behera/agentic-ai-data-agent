from typing import Optional

from pydantic import BaseModel, Field

from src.core.config import settings


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=settings.max_question_length)
    session_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")


class QueryResponse(BaseModel):
    answer: str
    session_id: str
    execution_time_ms: float
    agent_type: str
    success: bool
    sql: Optional[str] = None
    error: Optional[str] = None


class UploadResponse(BaseModel):
    success: bool
    filename: str
    file_id: Optional[str] = None
    rows: Optional[int] = None
    columns: Optional[list[str]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
