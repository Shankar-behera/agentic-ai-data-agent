"""Deterministic validation of LLM-generated SQL.

Defence in depth: this is the first layer. The second is the database itself
(read-only session + SELECT-only role + statement timeout), so a gap here is not a breach.
"""
import re

import sqlparse

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

FORBIDDEN_KEYWORDS = frozenset(
    """
    INSERT UPDATE DELETE MERGE DROP TRUNCATE ALTER CREATE GRANT REVOKE COPY INTO VACUUM ANALYZE
    REINDEX CLUSTER REFRESH CALL DO EXECUTE PREPARE DEALLOCATE LISTEN NOTIFY UNLISTEN LOCK SET
    RESET COMMENT SECURITY IMPORT BEGIN COMMIT ROLLBACK SAVEPOINT DISCARD CHECKPOINT
    """.split()
)

# Functions that read files, sleep, change server state or reach other servers.
FORBIDDEN_FUNCTIONS = frozenset(
    """
    set_config nextval setval currval lastval query_to_xml table_to_xml schema_to_xml database_to_xml
    cursor_to_xml query_to_xml_and_xmlschema dblink dblink_exec dblink_connect
    """.split()
)
FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"')
_DOLLAR_QUOTED = re.compile(r"\$([A-Za-z_]*)\$.*?\$\1\$", re.DOTALL)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SQLValidator:
    def __init__(self) -> None:
        self.allowed_commands = [c.upper() for c in settings.allowed_sql_commands]

    @staticmethod
    def _strip_noise(sql_text: str) -> str:
        """Remove comments, then blank out string literals / quoted identifiers."""
        no_comments = sqlparse.format(sql_text, strip_comments=True)
        no_dollar = _DOLLAR_QUOTED.sub("''", no_comments)
        no_strings = _STRING_LITERAL.sub("''", no_dollar)
        return _QUOTED_IDENT.sub('"x"', no_strings)

    def normalize(self, sql_query: str) -> str:
        """Comment-free, single-statement text without a trailing semicolon."""
        text = sqlparse.format(sql_query, strip_comments=True).strip()
        return text.rstrip(";").strip()

    def validate(self, sql_query: str) -> tuple[bool, str]:
        if not sql_query or not sql_query.strip():
            return False, "Empty query"
        if len(sql_query) > settings.max_sql_length:
            return False, f"Query exceeds {settings.max_sql_length} characters"
        if "\x00" in sql_query:
            return False, "Query contains a NUL byte"

        cleaned = self._strip_noise(sql_query)

        statements: list[str] = [s for s in sqlparse.split(cleaned) if s.strip().strip(";").strip()]
        if len(statements) != 1:
            return False, "Exactly one statement is allowed"
        if ";" in statements[0].strip().rstrip(";"):
            return False, "Multiple statements are not allowed"

        parsed = sqlparse.parse(statements[0])[0]
        first = parsed.token_first(skip_cm=True)
        first_word = (first.value if first is not None else "").upper()
        if first_word not in self.allowed_commands:
            return False, f"Query must start with one of: {', '.join(self.allowed_commands)}"

        for word in _WORD.findall(cleaned):
            upper = word.upper()
            if upper in FORBIDDEN_KEYWORDS:
                return False, f"Query contains forbidden keyword: {upper}"
            lower = word.lower()
            if lower in FORBIDDEN_FUNCTIONS or lower.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                return False, f"Query uses a forbidden function or object: {lower}"
        return True, "Query is safe"

    def is_read_only(self, sql_query: str) -> bool:
        ok, _ = self.validate(sql_query)
        return ok
