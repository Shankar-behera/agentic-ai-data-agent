import ipaddress
import json
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from src.core.config import settings
from src.core.exceptions import DataProcessingError, ToolExecutionError, ValidationError
from src.core.logging import get_logger
from src.security.sandbox import Sandbox

logger = get_logger(__name__)

SUPPORTED_FORMATS = ("csv", "json", "parquet")
READABLE_EXTENSIONS = (".csv", ".json", ".parquet", ".xlsx")
MAX_ROWS_FOR_TRANSFORM = 1_000_000


class ETLTools:
    """Extract/transform helpers. Every path and URL is treated as untrusted (it comes from an LLM)."""

    def __init__(self, base_output_dir: str | None = None):
        self.base_dir = Path(base_output_dir or settings.data_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── guards ─────────────────────────────────────────────────
    
    def _confine(self, relative: str, *, must_exist: bool = False) -> Path:
        """Resolve ``relative`` inside base_dir; reject absolute paths and any traversal."""
        if not relative or "\x00" in relative:
            raise ValidationError("Invalid path")

        clean_rel = relative.strip().replace("\\", "/")
        # Only strip a leading "data/" if the path does not attempt traversal
        if clean_rel.lower().startswith("data/") and ".." not in clean_rel:
            clean_rel = clean_rel[5:]

        candidate = Path(clean_rel)
        if not candidate.is_absolute():
            candidate = self.base_dir / candidate
        resolved = candidate.resolve()
        if resolved != self.base_dir and self.base_dir not in resolved.parents:
            raise ValidationError("Path escapes the data directory")

        if must_exist and not resolved.exists():
            # If the LLM only provided a bare filename (e.g. "extracted_data.csv" or "vehicles.csv"),
            # check standard subdirectories inside data/
            if "/" not in clean_rel and ".." not in clean_rel:
                for sub in ("extract", "uploads", "seed", "transform"):
                    alt = (self.base_dir / sub / clean_rel).resolve()
                    if self.base_dir in alt.parents and alt.exists():
                        return alt
            raise ValidationError("File not found")
        return resolved
    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValidationError("Only absolute http(s) URLs are allowed")
        host = parsed.hostname.lower()
        allowed = [h.lower() for h in settings.etl_allowed_hosts]
        if not any(host == a or host.endswith("." + a) for a in allowed):
            raise ValidationError(f"Host '{host}' is not in ETL_ALLOWED_HOSTS")
        if not settings.etl_allow_private_hosts:
            try:
                addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
            except socket.gaierror as e:
                raise ValidationError(f"Cannot resolve host '{host}'") from e
            for addr in addresses:
                if not ipaddress.ip_address(addr).is_global:
                    raise ValidationError("URL resolves to a non-public address")
        return url

    @staticmethod
    def _write(df: pd.DataFrame, path: Path, fmt: str) -> None:
        if fmt == "csv":
            df.to_csv(path, index=False)
        elif fmt == "json":
            df.to_json(path, orient="records", lines=True)
        elif fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            raise ValidationError(f"Unsupported format: {fmt}")

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        ext = path.suffix.lower()
        if ext == ".csv":
            return pd.read_csv(path, nrows=MAX_ROWS_FOR_TRANSFORM)
        if ext == ".json":
            return pd.read_json(path, lines=True, nrows=MAX_ROWS_FOR_TRANSFORM)
        if ext == ".parquet":
            return pd.read_parquet(path)
        if ext == ".xlsx":
            return pd.read_excel(path, nrows=MAX_ROWS_FOR_TRANSFORM)
        raise ValidationError(f"Unsupported file format: {ext}")

    # ── tools ──────────────────────────────────────────────────
    def extract_load(self, url: str, output_folder: str, format: str) -> dict[str, Any]:  # noqa: A002
        if format not in SUPPORTED_FORMATS:
            raise ValidationError(f"Unsupported format: {format}")
        self.validate_url(url)
        out_dir = self._confine(output_folder or "extract")
        limit = settings.etl_max_download_mb * 1024 * 1024

        try:
            # Redirects are refused: a redirect could point an allow-listed host at an internal address.
            with requests.get(url, timeout=30, allow_redirects=False, stream=True) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > limit:
                        raise ValidationError(f"Response larger than {settings.etl_max_download_mb}MB")
                    chunks.append(chunk)
            data = json.loads(b"".join(chunks))
        except requests.exceptions.RequestException as e:
            raise ToolExecutionError(f"Failed to fetch data from API: {e}") from e
        except ValueError as e:
            raise DataProcessingError(f"Response was not valid JSON: {e}") from e

        if isinstance(data, list):
            records: Any = data
        elif isinstance(data, dict):
            records = data.get("results")
            if records is None:
                records = next((data[k] for k in ("data", "items", "rows", "content") if k in data), [data])
        else:
            raise DataProcessingError("Unexpected JSON structure")

        df = pd.json_normalize(records)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"extracted_data.{format}"
        self._write(df, target, format)
        rel = os.path.relpath(target, self.base_dir)
        return {
            "status": "success",
            "filename": rel,
            "rows": len(df),
            "columns": [str(c) for c in df.columns],
            "message": f"Extracted {len(df)} rows to {rel}",
        }

    def transform_load_context(self, file_path: str) -> dict[str, Any]:
        path = self._confine(file_path, must_exist=True)
        if path.suffix.lower() not in READABLE_EXTENSIONS:
            raise ValidationError(f"Unsupported file format: {path.suffix}")
        try:
            df = self._read(path)
        except ValidationError:
            raise
        except Exception as e:
            raise DataProcessingError(f"Failed to read file: {e}") from e
        return {
            "file_path": os.path.relpath(path, self.base_dir),
            "rows": len(df),
            "columns": [str(c) for c in df.columns],
            "dtypes": df.dtypes.astype(str).to_dict(),
            "sample_data": df.head(3).to_dict(orient="records"),
            "is_empty": df.empty,
            "shape": df.shape,
        }

    def execute_pandas_code(self, code: str, context: dict[str, Any]) -> dict[str, Any]:
        source = self._confine(context["file_path"], must_exist=True)
        fmt = context.get("output_format", "csv")
        if fmt not in SUPPORTED_FORMATS:
            raise ValidationError(f"Unsupported format: {fmt}")
        df = self._read(source)

        result_df = Sandbox().run_dataframe(code, df)  # raises SecurityError / ToolExecutionError
        if result_df is None:
            return {"status": "warning", "message": "Code executed but no DataFrame was produced"}

        out_dir = self._confine("transform")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"transformed_data.{fmt}"
        self._write(result_df, target, fmt)
        rel = os.path.relpath(target, self.base_dir)
        return {
            "status": "success",
            "filename": rel,
            "rows": len(result_df),
            "columns": [str(c) for c in result_df.columns],
            "message": f"Transformed {len(result_df)} rows into {rel}",
        }
