import os
from typing import Any, Optional

import pandas as pd


class FileTools:
    @staticmethod
    def read_csv(file_path: str, **kwargs: Any) -> pd.DataFrame:
        return pd.read_csv(file_path, **kwargs)

    @staticmethod
    def read_json(file_path: str, **kwargs: Any) -> pd.DataFrame:
        return pd.read_json(file_path, **kwargs)

    @staticmethod
    def read_parquet(file_path: str, **kwargs: Any) -> pd.DataFrame:
        return pd.read_parquet(file_path, **kwargs)

    @staticmethod
    def read_excel(file_path: str, **kwargs: Any) -> pd.DataFrame:
        return pd.read_excel(file_path, **kwargs)

    @staticmethod
    def save_csv(df: pd.DataFrame, file_path: str, **kwargs: Any) -> None:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        df.to_csv(file_path, index=False, **kwargs)

    @staticmethod
    def save_json(df: pd.DataFrame, file_path: str, **kwargs: Any) -> None:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        df.to_json(file_path, orient="records", lines=True, **kwargs)

    @staticmethod
    def get_file_info(file_path: str) -> dict[str, Any]:
        stats = os.stat(file_path)
        return {
            "name": os.path.basename(file_path),
            "size_bytes": stats.st_size,
            "modified": stats.st_mtime,
            "extension": os.path.splitext(file_path)[1].lower(),
        }

    @staticmethod
    def list_files(directory: str, extension: Optional[str] = None) -> list[str]:
        files = os.listdir(directory)
        if extension:
            files = [f for f in files if f.endswith(extension)]
        return files
