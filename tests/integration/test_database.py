import psycopg2
import pytest

from src.agents.sql_analyst import SQLAnalystAgent
from src.core.config import settings
from src.core.database import DatabaseUtil
from tests.conftest import FakeLLM

pytestmark = pytest.mark.integration


def test_readonly_query_returns_columns_and_rows(live_db):
    r = live_db.execute_readonly("SELECT status, COUNT(*) AS n FROM rides GROUP BY status ORDER BY n DESC")
    assert r.columns == ["status", "n"] and r.rows[0][0] == "completed" and not r.truncated


def test_row_cap_marks_truncation(live_db):
    r = live_db.execute_readonly("SELECT ride_id FROM rides", max_rows=7)
    assert len(r.rows) == 7 and r.truncated


def test_database_refuses_writes_even_if_validator_were_bypassed(live_db):
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        live_db.execute_readonly("DELETE FROM payments")
    assert live_db.execute_readonly("SELECT COUNT(*) FROM payments").rows[0][0] == 16073


def test_data_modifying_cte_is_refused_by_the_database(live_db):
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        live_db.execute_readonly("WITH x AS (DELETE FROM payments RETURNING *) SELECT count(*) FROM x")


def test_statement_timeout_is_enforced(live_db, monkeypatch):
    monkeypatch.setattr(settings, "db_statement_timeout_ms", 300)
    with pytest.raises(psycopg2.errors.QueryCanceled):
        live_db.execute_readonly("SELECT pg_sleep(3)")


def test_real_error_is_not_masked_and_pool_survives(live_db):
    # Regression: a failed query used to raise PoolError("trying to put unkeyed connection").
    for _ in range(15):  # more than the pool size, so a leaked connection would exhaust it
        with pytest.raises(psycopg2.errors.UndefinedColumn):
            live_db.execute_readonly("SELECT nonexistent_col FROM rides")
    assert live_db.execute_readonly("SELECT 1").rows == [(1,)]


def test_schema_text_has_relationships_and_no_pii_values(live_db):
    live_db.invalidate_schema_cache()
    text = live_db.get_schema_details()
    assert "Table: rides" in text and "Relationships:" in text and "FOREIGN KEY" in text
    assert "@example.com" not in text and "+1" not in text  # emails / phone numbers are never sampled


def test_sql_agent_against_real_database():
    llm = FakeLLM(
        [
            ("Rewrite the question", "total completed revenue by city"),
            ("Write ONE PostgreSQL query", "SELECT u.city, ROUND(SUM(p.amount),2) AS revenue FROM payments p JOIN users u ON u.user_id=p.user_id WHERE p.payment_status='completed' GROUP BY u.city ORDER BY revenue DESC LIMIT 3"),
            ("Result of the SQL query", "Toronto leads."),
        ]
    )
    out = SQLAnalystAgent(db=DatabaseUtil(readonly=True), llm=llm).invoke("revenue by city")
    assert out["success"] and out["result"].splitlines()[0] == "city | revenue" and "Toronto" in out["result"]


def test_destructive_sql_is_blocked_end_to_end_and_data_survives(live_db):
    llm = FakeLLM(
        [
            ("Rewrite the question", "x"),
            ("Write ONE PostgreSQL query", "WITH x AS (DELETE FROM payments RETURNING *) SELECT count(*) FROM x"),
        ]
    )
    out = SQLAnalystAgent(db=DatabaseUtil(readonly=True), llm=llm).invoke("delete everything")
    assert not out["success"] and "safety validation" in out["answer"]
    assert live_db.execute_readonly("SELECT COUNT(*) FROM payments").rows[0][0] == 16073
