import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import psycopg2
from psycopg2 import InterfaceError, OperationalError, pool, sql
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Columns whose values are never forwarded to the LLM as sample data.
PII_COLUMN_HINTS = ("email", "phone", "license_plate", "password", "token", "ssn", "transaction_id")


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False
    elapsed_ms: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_text(self, max_chars: int = 3000) -> str:
        """Compact, column-labelled table suitable for an LLM prompt."""
        if not self.rows:
            return "Query returned 0 rows."
        lines = [" | ".join(self.columns)]
        for row in self.rows:
            lines.append(" | ".join("NULL" if v is None else str(v) for v in row))
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0] + "\n... (output truncated)"
        if self.truncated:
            text += f"\n(Result limited to the first {len(self.rows)} rows.)"
        return text


class DatabaseUtil:
    """Thin psycopg2 pool wrapper.

    ``readonly=True`` uses the SELECT-only credentials (if configured) and opens every
    session in ``READ ONLY`` mode, so a bug in the SQL validator cannot modify data.
    The pool is created lazily so importing the app never requires a live database.
    """

    def __init__(self, readonly: bool = False):
        self.readonly = readonly
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._lock = threading.Lock()
        self._schema_cache: dict[str, tuple[float, str]] = {}

    # ── connection management ──────────────────────────────────
    def _dsn(self) -> dict[str, Any]:
        user = settings.effective_db_user if self.readonly else settings.db_user
        password = settings.effective_db_password if self.readonly else settings.db_password.get_secret_value()
        return {
            "host": settings.db_host,
            "port": settings.db_port,
            "user": user,
            "password": password,
            "dbname": settings.db_name,
            "connect_timeout": settings.db_connect_timeout,
            "application_name": "data-agent-ro" if self.readonly else "data-agent",
        }

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def _create_pool(self) -> pool.ThreadedConnectionPool:
        return pool.ThreadedConnectionPool(settings.db_pool_min, settings.db_pool_max, **self._dsn())

    def _get_pool(self) -> pool.ThreadedConnectionPool:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    self._pool = self._create_pool()
                    logger.info("db_pool_initialized", readonly=self.readonly)
        return self._pool

    @contextmanager
    def get_connection(self) -> Iterator[Any]:
        p = self._get_pool()
        conn = p.getconn()
        broken = False
        try:
            conn.set_session(readonly=self.readonly, autocommit=False)
            yield conn
        except (OperationalError, InterfaceError):
            broken = True
            raise
        finally:
            # Exactly one putconn per getconn; never let cleanup mask the real exception.
            try:
                if broken or conn.closed:
                    p.putconn(conn, close=True)
                else:
                    conn.rollback()
                    p.putconn(conn)
            except Exception as cleanup_error:  # pragma: no cover - defensive
                logger.warning("db_connection_cleanup_failed", error=str(cleanup_error))

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None

    def ping(self) -> bool:
        """Cheap liveness probe that bypasses the pool and retries."""
        try:
            conn = psycopg2.connect(**{**self._dsn(), "connect_timeout": 3})
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return True
            finally:
                conn.close()
        except Exception:
            return False

    test_connection = ping

    # ── query execution ────────────────────────────────────────
    def execute_query(self, query: Any, params: Optional[tuple[Any, ...]] = None) -> list[tuple[Any, ...]]:
        with self.get_connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def execute_non_query(self, query: str, params: Optional[tuple[Any, ...]] = None) -> int:
        if self.readonly:
            raise PermissionError("execute_non_query is not available on a read-only connection")
        with self.get_connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
            return cur.rowcount

    def execute_readonly(self, query: str, max_rows: Optional[int] = None) -> QueryResult:
        """Run LLM-generated SQL with a statement timeout and a hard row cap."""
        limit = max_rows or settings.db_max_rows
        started = time.perf_counter()
        with self.get_connection() as conn:
            conn.set_session(readonly=True, autocommit=False)
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {int(settings.db_statement_timeout_ms)}")
                cur.execute(query)
                if cur.description is None:
                    return QueryResult([], [], False, (time.perf_counter() - started) * 1000)
                columns = [d.name for d in cur.description]
                rows = cur.fetchmany(limit + 1)
        truncated = len(rows) > limit
        return QueryResult(columns, rows[:limit], truncated, (time.perf_counter() - started) * 1000)

    # ── schema introspection (cached, PII-masked) ──────────────
    def get_schema_details(self, schema_name: str = "public") -> str:
        cached = self._schema_cache.get(schema_name)
        if cached and time.monotonic() - cached[0] < settings.schema_cache_ttl_s:
            return cached[1]

        columns_sql = """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """
        fk_sql = """
            SELECT conrelid::regclass::text, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE contype = 'f' AND connamespace = %s::regnamespace
            ORDER BY 1
        """
        with self.get_connection() as conn, conn.cursor() as cur:
            cur.execute(columns_sql, (schema_name,))
            rows = cur.fetchall()
            if not rows:
                return f"No tables found in schema '{schema_name}'."

            tables: dict[str, list[tuple[str, str]]] = {}
            for table, column, dtype in rows:
                tables.setdefault(table, []).append((column, dtype))

            fks: list[tuple[str, str]] = []
            try:
                cur.execute(fk_sql, (schema_name,))
                fks = cur.fetchall()
            except Exception as e:
                conn.rollback()
                logger.debug("fk_introspection_failed", error=str(e))

            out = [f"Database Schema: {schema_name}"]
            for table, cols in tables.items():
                out.append(f"\nTable: {table}")
                out.extend(f"  {c} ({t})" for c, t in cols)
                if settings.schema_sample_rows > 0:
                    sample = self._sample_rows(cur, conn, schema_name, table, [c for c, _ in cols])
                    if sample:
                        out.append(f"  Sample rows ({table}):")
                        out.extend(f"    {r}" for r in sample)
            if fks:
                out.append("\nRelationships:")
                out.extend(f"  {t}: {d}" for t, d in fks)

        text = "\n".join(out)
        self._schema_cache[schema_name] = (time.monotonic(), text)
        return text

    @staticmethod
    def _sample_rows(cur: Any, conn: Any, schema: str, table: str, columns: list[str]) -> list[dict[str, Any]]:
        safe_cols = [c for c in columns if not any(h in c.lower() for h in PII_COLUMN_HINTS)]
        if not safe_cols:
            return []
        try:
            q = sql.SQL("SELECT {} FROM {}.{} LIMIT %s").format(
                sql.SQL(", ").join(sql.Identifier(c) for c in safe_cols),
                sql.Identifier(schema),
                sql.Identifier(table),
            )
            cur.execute(q, (settings.schema_sample_rows,))
            return [dict(zip(safe_cols, r, strict=False)) for r in cur.fetchall()]
        except Exception as e:
            conn.rollback()
            logger.warning("schema_sample_failed", table=table, error=str(e))
            return []

    def invalidate_schema_cache(self) -> None:
        self._schema_cache.clear()
