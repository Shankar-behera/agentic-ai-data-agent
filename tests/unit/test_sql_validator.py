import pytest

from src.security.sql_validator import SQLValidator

v = SQLValidator()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT 1;",
        "select count(*) from rides where status = 'completed'",
        "SELECT\n  city,\n  COUNT(*)\nFROM users\nGROUP BY city",
        "WITH t AS (SELECT * FROM rides) SELECT count(*) FROM t",
        "SELECT * FROM users WHERE phone LIKE '%0x%'",          # was a false positive
        "-- top riders\nSELECT rider_id FROM rides LIMIT 5",      # leading comment is stripped, not rejected
        "SELECT updated_at, created_by FROM t",                   # substrings of keywords are fine
        "SELECT * FROM rides WHERE cancellation_reason = 'DELETE me'",  # keyword inside a literal
        'SELECT "delete" FROM t',                                  # quoted identifier
    ],
)
def test_accepts_legitimate_queries(sql):
    ok, reason = v.validate(sql)
    assert ok, reason


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "DROP TABLE users",
        "DELETE FROM payments",
        "SELECT 1; DROP TABLE users;",
        "SELECT 1; SELECT 2",
        "WITH x AS (DELETE FROM payments RETURNING *) SELECT count(*) FROM x",  # data-modifying CTE
        "WITH x AS (UPDATE rides SET fare = 0 RETURNING *) SELECT * FROM x",
        "SELECT * INTO backup_users FROM users",                                # creates a table
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_sleep(30)",
        "SELECT * FROM pg_shadow",
        "SELECT lo_import('/etc/passwd')",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT nextval('s')",
        "SELECT * FROM dblink('host=x', 'select 1') AS t(a int)",
        "SELECT 1; COPY (SELECT 1) TO PROGRAM 'id'",
        "SELECT 1 /* x */; DROP TABLE t",
        "EXPLAIN ANALYZE DELETE FROM rides",
        "COPY users TO '/tmp/x'",
        "SELECT * FROM rides FOR UPDATE",
        "SELECT $$x$$; DROP TABLE t",
        "x" * 6000,
    ],
)
def test_rejects_dangerous_queries(sql):
    ok, reason = v.validate(sql)
    assert not ok, f"should have been rejected: {sql[:60]!r}"
    assert reason


def test_normalize_strips_comments_and_semicolon():
    assert v.normalize("SELECT 1; -- done") == "SELECT 1"
