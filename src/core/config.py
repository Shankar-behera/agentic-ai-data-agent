from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.exceptions import ConfigurationError


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env file).

    Variable names are the upper-cased field names, e.g. ``DB_HOST``.
    """

    # Application
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: Optional[bool] = None  # None -> JSON in production, console otherwise
    request_timeout: int = 120

    # LLM (Ollama)
    llm_provider: str = "ollama"
    llm_model: str = "phi3:mini"
    ollama_base_url: str = "http://localhost:11434"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_num_ctx: int = 4096
    llm_timeout: int = 120
    max_retries: int = Field(2, ge=0, le=5)  # LLM transport/parse retries and SQL self-correction attempts

    # Agent
    max_agent_iterations: int = 5
    max_question_length: int = Field(500, ge=1, le=5000)
    sql_curate_question: bool = False  # extra LLM call that rewrites the question; slow and low-value on small models
    llm_safety_check: bool = False  # optional second LLM opinion; deterministic validation always runs

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: SecretStr = SecretStr("postgres")
    db_name: str = "rides_db"
    # The agent executes LLM-written SQL with these credentials. Use a SELECT-only role in production.
    db_readonly_user: Optional[str] = None
    db_readonly_password: Optional[SecretStr] = None
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_connect_timeout: int = 5
    db_statement_timeout_ms: int = 15_000
    db_max_rows: int = 200
    schema_cache_ttl_s: int = 300
    schema_sample_rows: int = Field(2, ge=0, le=5)

    # API
    api_host: str = "0.0.0.0"  # noqa: S104 - container-friendly default, override on bare metal
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    api_key: Optional[SecretStr] = None  # required when APP_ENV=production
    rate_limit_per_minute: int = Field(30, ge=0)  # 0 disables
    max_concurrent_queries: int = Field(2, ge=1)
    queue_timeout_s: float = 5.0

    # Uploads / ETL
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = [".csv", ".json", ".parquet", ".xlsx"]
    data_dir: str = "data"
    etl_allowed_hosts: list[str] = ["pokeapi.co"]
    etl_allow_private_hosts: bool = False  # never enable in production (SSRF)
    etl_max_download_mb: int = 10
    sandbox_timeout_s: int = 20
    sandbox_memory_mb: int = 2048

    # SQL safety
    allowed_sql_commands: list[str] = ["SELECT", "WITH"]
    max_sql_length: int = 5000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.is_production

    @property
    def effective_db_user(self) -> str:
        return self.db_readonly_user or self.db_user

    @property
    def effective_db_password(self) -> str:
        if self.db_readonly_user and self.db_readonly_password:
            return self.db_readonly_password.get_secret_value()
        return self.db_password.get_secret_value()

    def validate_for_production(self) -> None:
        """Fail fast on unsafe production configuration."""
        if not self.is_production:
            return
        problems = []
        if not self.api_key or not self.api_key.get_secret_value():
            problems.append("API_KEY must be set")
        if not self.db_readonly_user:
            problems.append("DB_READONLY_USER must be set (the agent must not run SQL as the owner role)")
        if self.etl_allow_private_hosts:
            problems.append("ETL_ALLOW_PRIVATE_HOSTS must be false")
        if problems:
            raise ConfigurationError("Unsafe production configuration: " + "; ".join(problems))


settings = Settings()