from typing import Any, Optional

import pandas as pd


class PandasTools:
    @staticmethod
    def describe(df: pd.DataFrame) -> dict[str, Any]:
        return {
            "shape": df.shape,
            "columns": list(df.columns),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "null_counts": df.isnull().sum().to_dict(),
            "sample": df.head(5).to_dict(orient="records"),
        }

    @staticmethod
    def groupby_agg(df: pd.DataFrame, group_col: str, agg_col: str, agg_func: str = "mean") -> pd.DataFrame:
        return df.groupby(group_col)[agg_col].agg(agg_func).reset_index()

    @staticmethod
    def filter_df(df: pd.DataFrame, column: str, operator: str, value: Any) -> pd.DataFrame:
        if operator == "==":
            return df[df[column] == value]
        elif operator == ">":
            return df[df[column] > value]
        elif operator == "<":
            return df[df[column] < value]
        elif operator == ">=":
            return df[df[column] >= value]
        elif operator == "<=":
            return df[df[column] <= value]
        elif operator == "!=":
            return df[df[column] != value]
        elif operator == "contains":
            return df[df[column].astype(str).str.contains(str(value), case=False)]
        else:
            return df

    @staticmethod
    def sort_df(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        return df.sort_values(by=column, ascending=ascending)

    @staticmethod
    def drop_duplicates(df: pd.DataFrame, subset: Optional[list[str]] = None) -> pd.DataFrame:
        return df.drop_duplicates(subset=subset)

    @staticmethod
    def fill_missing(df: pd.DataFrame, column: str, value: Any) -> pd.DataFrame:
        df = df.copy()
        df[column] = df[column].fillna(value)
        return df

    @staticmethod
    def to_csv(df: pd.DataFrame, path: str) -> None:
        df.to_csv(path, index=False)

    @staticmethod
    def to_json(df: pd.DataFrame, path: str) -> None:
        df.to_json(path, orient="records", lines=True)
