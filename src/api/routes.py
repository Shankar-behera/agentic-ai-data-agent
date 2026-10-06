import os
import time
import uuid
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, UploadFile

from src.agents.data_agent import DataAgent, get_data_agent
from src.api.dependencies import query_slot, rate_limit, require_api_key
from src.api.schemas import QueryRequest, QueryResponse, UploadResponse
from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.logging import get_logger, get_request_id
from src.security.file_validator import FileValidator

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key), Depends(rate_limit)])

CHUNK = 1024 * 1024


# Plain `def` (not `async def`): the agent call is blocking and long-running, so FastAPI runs it
# in its threadpool and the event loop keeps serving /health and other requests.
@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    _slot: None = Depends(query_slot),
    agent: DataAgent = Depends(get_data_agent),
) -> QueryResponse:
    started = time.perf_counter()
    session_id = request.session_id or get_request_id()
    logger.info("query_received", chars=len(request.question))
    result = agent.invoke(request.question)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info("query_completed", success=result["success"], route=result.get("route"), ms=round(elapsed_ms, 1))
    return QueryResponse(
        answer=result["answer"],
        session_id=session_id,
        execution_time_ms=round(elapsed_ms, 2),
        agent_type=result.get("route") or "unknown",
        success=result["success"],
        sql=result.get("sql"),
        error=result.get("error"),
    )


def _preview(path: str) -> tuple[Optional[int], Optional[list[str]]]:
    """Row count + column names; failures are non-fatal (the upload itself succeeded)."""
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            rows, columns = 0, None
            for chunk in pd.read_csv(path, chunksize=50_000):
                columns = columns or [str(c) for c in chunk.columns]
                rows += len(chunk)
            return rows, columns
        if ext == ".json":
            df = pd.read_json(path, lines=True)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        elif ext == ".xlsx":
            df = pd.read_excel(path)
        else:
            return None, None
        return len(df), [str(c) for c in df.columns]
    except Exception as e:  # noqa: BLE001
        logger.warning("upload_preview_failed", error=str(e)[:200])
        return None, None


@router.post("/upload", response_model=UploadResponse)
def upload_file(file: UploadFile = File(...), purpose: Optional[str] = Form(None)) -> UploadResponse:
    filename = file.filename or ""
    if not FileValidator.validate_extension(filename):
        raise ValidationError(f"File extension not allowed. Allowed: {settings.allowed_extensions}")

    file_id = str(uuid.uuid4())
    safe_name = FileValidator.sanitize_filename(filename)
    upload_dir = os.path.join(settings.data_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, f"{file_id}_{safe_name}")

    # Stream to disk in chunks and enforce the size cap while reading, not after.
    limit = settings.max_upload_size_mb * 1024 * 1024
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise ValidationError(f"File exceeds maximum size of {settings.max_upload_size_mb}MB")
                out.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise

    rows, columns = _preview(path)
    logger.info("file_uploaded", file_id=file_id, bytes=size, rows=rows)
    return UploadResponse(success=True, filename=safe_name, file_id=file_id, rows=rows, columns=columns)
