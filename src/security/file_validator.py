import os
import re

from src.core.config import settings

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class FileValidator:
    @staticmethod
    def validate_extension(filename: str) -> bool:
        ext = os.path.splitext(filename or "")[1].lower()
        return ext in settings.allowed_extensions

    @staticmethod
    def validate_size(file_size: int) -> bool:
        return file_size <= settings.max_upload_size_mb * 1024 * 1024

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        name = os.path.basename((filename or "").replace("\\", "/"))
        stem, ext = os.path.splitext(name)
        stem = _SAFE_CHARS.sub("_", stem).strip("._") or "upload"
        ext = _SAFE_CHARS.sub("", ext.lower())
        return f"{stem[:80]}{ext}"

    @staticmethod
    def get_allowed_extensions() -> list[str]:
        return list(settings.allowed_extensions)
