from typing import Any, Optional


class AppError(Exception):
    """Base class for all application errors that map to an HTTP response."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ConfigurationError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=500, details=details)


class ValidationError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=400, details=details)


class AuthenticationError(AppError):
    def __init__(self, message: str = "Invalid or missing API key", details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=401, details=details)


class RateLimitError(AppError):
    def __init__(self, message: str = "Too many requests", details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=429, details=details)


class DataProcessingError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=500, details=details)


class ToolExecutionError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=500, details=details)


class LLMError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=503, details=details)


class AgentExecutionError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=500, details=details)


class AgentTimeoutError(AgentExecutionError):
    def __init__(self, message: str = "Agent execution timed out", details: Optional[dict[str, Any]] = None):
        super().__init__(message, details)


class SecurityError(AppError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, status_code=403, details=details)
