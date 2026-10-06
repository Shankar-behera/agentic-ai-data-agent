import pytest

from src.agents.router import RouterAgent, heuristic_route
from src.agents.sql_analyst import SQLAnalystAgent, extract_sql
from src.core.config import settings
from src.core.database import QueryResult
from tests.conftest import FakeDB

CURATE = ("Rewrite the question", lambda p: p.split("Original:")[1].split("\n")[0].strip())
GEN = "Write ONE PostgreSQL query"
ANSWER = ("Result of the SQL query", "There were 3 completed rides.")


def agent(db, rules):
    from tests.conftest import FakeLLM

    llm = FakeLLM([CURATE, *rules, ANSWER])
    return SQLAnalystAgent(db=db, llm=llm), llm


def test_happy_path_returns_answer_and_sql():
    db = FakeDB([QueryResult(["n"], [(3,)])])
    a, _ = agent(db, [(GEN, "```sql\nSELECT COUNT(*) AS n FROM rides WHERE status='completed';\n```")])
    out = a.invoke("how many completed rides?")
    assert out["success"] and out["answer"] == "There were 3 completed rides."
    assert db.executed == ["SELECT COUNT(*) AS n FROM rides WHERE status='completed'"]  # normalised, no semicolon
    assert out["attempts"] == 1


def test_self_corrects_using_the_real_db_error():
    db = FakeDB([RuntimeError('column "ride_cost" does not exist'), QueryResult(["n"], [(3,)])])
    replies = iter(["SELECT ride_cost FROM rides", "SELECT fare FROM rides"])
    a, llm = agent(db, [(GEN, lambda p: next(replies))])
    out = a.invoke("total fare?")
    assert out["success"] and out["attempts"] == 2
    retry_prompt = [p for p in llm.prompts if "Your previous query failed" in p][0]
    assert 'column "ride_cost" does not exist' in retry_prompt and "SELECT ride_cost FROM rides" in retry_prompt


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(settings, "max_retries", 1)
    db = FakeDB([RuntimeError("boom 1"), RuntimeError("boom 2")])
    a, _ = agent(db, [(GEN, "SELECT nope FROM rides")])
    out = a.invoke("q")
    assert not out["success"] and out["attempts"] == 2 and out["error"] == "SQL execution failed"


def test_production_hides_database_error_text(monkeypatch):
    monkeypatch.setattr(settings, "max_retries", 0)
    monkeypatch.setattr(settings, "app_env", "production")
    a, _ = agent(FakeDB([RuntimeError('relation "secret_table" does not exist')]), [(GEN, "SELECT 1 FROM secret_table")])
    out = a.invoke("q")
    assert not out["success"] and "secret_table" not in out["answer"]


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DROP TABLE users",
        "WITH x AS (DELETE FROM payments RETURNING *) SELECT count(*) FROM x",
        "SELECT pg_read_file('/etc/passwd')",
    ],
)
def test_unsafe_sql_never_reaches_the_database(bad_sql):
    db = FakeDB([])  # any execute call would raise IndexError
    a, _ = agent(db, [(GEN, bad_sql)])
    out = a.invoke("q")
    assert not out["success"] and out["is_safe"] == "No" and db.executed == []
    assert "safety validation" in out["answer"]


def test_empty_result_short_circuits_without_llm_answer():
    a, llm = agent(FakeDB([QueryResult(["n"], [])]), [(GEN, "SELECT 1 WHERE false")])
    out = a.invoke("q")
    assert out["success"] and "no matching rows" in out["answer"]
    assert not any("Result of the SQL query" in p for p in llm.prompts)


def test_llm_failure_during_answering_still_returns_data():
    from tests.conftest import FakeLLM

    llm = FakeLLM([CURATE, (GEN, "SELECT 1")])  # no rule for the answer prompt
    out = SQLAnalystAgent(db=FakeDB([QueryResult(["x"], [(1,)])]), llm=llm).invoke("q")
    assert out["success"] and "x\n1" in out["answer"]


def test_schema_failure_is_reported_not_swallowed():
    class BrokenDB(FakeDB):
        def get_schema_details(self, schema_name="public"):
            raise ConnectionError("db down")

    a, _ = agent(BrokenDB([]), [])
    out = a.invoke("q")
    assert not out["success"] and "schema" in out["answer"].lower()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SELECT 1", "SELECT 1"),
        ("```sql\nSELECT 1;\n```", "SELECT 1"),
        ("Sure! Here you go:\nSELECT a FROM t;\nThis returns a.", "SELECT a FROM t"),
        ("with x as (select 1) select * from x", "with x as (select 1) select * from x"),
    ],
)
def test_extract_sql(raw, expected):
    assert extract_sql(raw) == expected


def test_query_result_to_text_has_headers_and_truncation_note():
    r = QueryResult(["a", "b"], [(1, None), (2, "x")], truncated=True)
    text = r.to_text()
    assert text.splitlines()[0] == "a | b" and "NULL" in text and "limited" in text


def test_router_falls_back_to_keywords_when_llm_fails(fake_llm_factory):
    r = RouterAgent(llm=fake_llm_factory([]))  # every call raises
    assert r.route("download data from the API")["intent"] == "etl"
    assert r.route("average fare by city")["intent"] == "sql"
    assert heuristic_route("convert it to parquet") == "etl"


def test_router_uses_llm_answer(fake_llm_factory):
    r = RouterAgent(llm=fake_llm_factory([("Classify the request", '{"answer": "etl", "comments": "x"}')]))
    assert r.route("anything")["intent"] == "etl"


def test_only_the_first_statement_is_ever_used():
    db = FakeDB([QueryResult(["x"], [(1,)])])
    a, _ = agent(db, [(GEN, "SELECT 1; DELETE FROM rides")])
    out = a.invoke("q")
    assert out["success"] and db.executed == ["SELECT 1"]
