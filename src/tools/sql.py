from src.core.database import DatabaseUtil
from src.security.sql_validator import SQLValidator


class SQLTools:
    """Standalone helper. Uses the same guardrails as the SQL agent: validator + read-only session."""

    def __init__(self, db: DatabaseUtil | None = None):
        self.db = db or DatabaseUtil(readonly=True)
        self.validator = SQLValidator()

    def get_schema(self, schema_name: str = "public") -> str:
        return self.db.get_schema_details(schema_name)

    def execute_query(self, query: str) -> str:
        ok, reason = self.validator.validate(query)
        if not ok:
            return f"Query rejected: {reason}"
        try:
            return self.db.execute_readonly(self.validator.normalize(query)).to_text()
        except Exception as e:  # noqa: BLE001
            return f"Error executing query: {e}"

    def test_connection(self) -> bool:
        return self.db.ping()
