"""Run LLM-generated pandas code in an isolated child process."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from src.core.config import settings
from src.core.exceptions import SecurityError, ToolExecutionError
from src.core.logging import get_logger
from src.security.code_validator import CodeValidator

logger = get_logger(__name__)

RUNNER = Path(__file__).with_name("_sandbox_runner.py")

# Windows requires SystemRoot and PATH to load Python/NumPy/PyArrow DLLs in child processes
_SAFE_ENV_KEYS = ("SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "Path", "TEMP", "TMP", "HOME", "LANG")


class Sandbox:
    def __init__(self, timeout_s: int | None = None, memory_mb: int | None = None):
        self.validator = CodeValidator()
        self.timeout_s = timeout_s or settings.sandbox_timeout_s
        self.memory_mb = memory_mb or settings.sandbox_memory_mb

    def run_dataframe(self, code: str, df: pd.DataFrame) -> pd.DataFrame | None:
        """Execute ``code`` with ``df`` in scope. Returns the resulting DataFrame, or None."""
        ok, reason = self.validator.check(code)
        if not ok:
            raise SecurityError(f"Generated code rejected: {reason}")

        safe_env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}

        with tempfile.TemporaryDirectory(prefix="sandbox_") as workdir:
            (Path(workdir) / "code.py").write_text(code, encoding="utf-8")
            df.to_parquet(Path(workdir) / "in.parquet", index=False)
            try:
                proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    [sys.executable, "-I", str(RUNNER), workdir, str(self.timeout_s), str(self.memory_mb)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s + 5,
                    env=safe_env,
                    cwd=workdir,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise ToolExecutionError(f"Generated code exceeded {self.timeout_s}s limit") from e

            last_line = (proc.stdout.strip().splitlines() or [""])[-1]
            try:
                report = json.loads(last_line)
            except json.JSONDecodeError:
                err_detail = (proc.stderr or proc.stdout or "").strip()[-300:]
                logger.error("sandbox_no_json", returncode=proc.returncode, stderr=err_detail)
                if proc.returncode < 0:
                    raise ToolExecutionError("Generated code was terminated by resource limits") from None
                raise ToolExecutionError(f"Sandbox produced no result ({err_detail})") from None

            if report.get("status") == "error":
                raise ToolExecutionError(f"Generated code failed: {report.get('message', 'unknown error')}")
            if report.get("status") != "ok":
                return None
            return pd.read_parquet(Path(workdir) / "out.parquet")