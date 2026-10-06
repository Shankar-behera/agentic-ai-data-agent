import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import router
from src.api.schemas import HealthResponse
from src.core.config import settings
from src.core.database import DatabaseUtil
from src.core.exceptions import AppError
from src.core.logging import clear_request_id, configure_logging, get_logger, set_request_id
from src.llm.provider import create_llm_provider

VERSION = "2.1.0"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

configure_logging(settings.log_level, settings.json_logs)
logger = get_logger(__name__)

# Readiness probes share one lightweight DB handle (no pool is created for ping()).
_probe_db = DatabaseUtil(readonly=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.validate_for_production()  # refuse to boot with an unsafe production config
    logger.info("startup", env=settings.app_env, model=settings.llm_model, version=VERSION)
    yield
    logger.info("shutdown")


app = FastAPI(
    title="Agentic AI Data Agent",
    description="Local AI data agent: natural-language SQL analytics and safe ETL, powered by Ollama.",
    version=VERSION,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
    set_request_id(request_id)
    started = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:
        logger.error("unhandled_exception", path=request.url.path, exc_info=True)
        response = JSONResponse(
            status_code=500, content={"error": "Internal server error", "request_id": request_id}
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    if request.url.path not in ("/health", "/ready"):  # keep probe noise out of the logs
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - started) * 1000, 1),
        )
    clear_request_id()
    return response


app.include_router(router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    level = logger.warning if exc.status_code < 500 else logger.error
    level("app_error", status=exc.status_code, message=exc.message)
    headers = {}
    if exc.status_code == 429 and "retry_after_s" in exc.details:
        headers["Retry-After"] = str(int(exc.details["retry_after_s"]) + 1)
    message = exc.message if exc.status_code < 500 else "Internal server error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": message, "details": exc.details if exc.status_code < 500 else {}},
        headers=headers,
    )


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness: the process is up. Does not touch Ollama or Postgres."""
    return HealthResponse(status="healthy", version=VERSION)


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    """Readiness: database reachable and the configured model is available in Ollama."""
    llm = create_llm_provider().health_check()
    components = {
        "database": _probe_db.ping(),
        "ollama": llm["reachable"],
        "model": llm["model_available"],
    }
    ok = all(components.values())
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "components": components})


@app.get("/", tags=["ops"])
def root() -> dict[str, Any]:
    return {
        "name": "Agentic AI Data Agent",
        "version": VERSION,
        "docs": None if settings.is_production else "/docs",
    }


def main() -> None:
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        timeout_keep_alive=15,
    )


if __name__ == "__main__":
    main()
