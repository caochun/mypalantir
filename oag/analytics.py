from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .store import Store


def describe(store: Store, object_type: str, column: str | None = None) -> dict:
    rows = store.query(object_type)
    if not rows:
        return {"error": f"{object_type} has no data"}
    df = pd.DataFrame(rows).drop(columns=["_id"], errors="ignore")

    if column:
        if column not in df.columns:
            return {"error": f"Unknown column: {column}", "columns": list(df.columns)}
        series = df[column]
        if pd.api.types.is_numeric_dtype(series):
            desc = series.describe().to_dict()
            return {k: _clean(v) for k, v in desc.items()}
        else:
            return {
                "count": int(series.count()),
                "unique": int(series.nunique()),
                "top": _clean(series.mode().iloc[0]) if not series.mode().empty else None,
                "freq": int(series.value_counts().iloc[0]) if not series.empty else 0,
                "sample": [_clean(x) for x in series.head(5).tolist()],
            }
    else:
        summary = {
            "rows": len(df),
            "columns": list(df.columns),
            "numeric": [],
            "text": [],
        }
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                summary["numeric"].append(col)
            else:
                summary["text"].append(col)
        return summary


def pivot(store: Store, object_type: str, index: str, columns: str,
          values: str, aggfunc: str = "mean") -> dict:
    rows = store.query(object_type)
    if not rows:
        return {"error": f"{object_type} has no data"}
    df = pd.DataFrame(rows).drop(columns=["_id"], errors="ignore")

    for col in [index, columns, values]:
        if col not in df.columns:
            return {"error": f"Unknown column: {col}", "columns": list(df.columns)}

    agg_map = {"mean": "mean", "sum": "sum", "count": "count", "min": "min", "max": "max"}
    func = agg_map.get(aggfunc, "mean")

    try:
        pt = pd.pivot_table(df, values=values, index=index, columns=columns,
                            aggfunc=func, fill_value=0)
        result = {
            "index": [_clean(x) for x in pt.index.tolist()],
            "columns": [_clean(x) for x in pt.columns.tolist()],
            "data": [[_clean(cell) for cell in row] for row in pt.values.tolist()],
        }
        return result
    except Exception as e:
        return {"error": str(e)}


def distribution(store: Store, object_type: str, column: str,
                 bins: int = 10) -> dict:
    rows = store.query(object_type)
    if not rows:
        return {"error": f"{object_type} has no data"}
    df = pd.DataFrame(rows).drop(columns=["_id"], errors="ignore")

    if column not in df.columns:
        return {"error": f"Unknown column: {column}", "columns": list(df.columns)}

    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return {"error": f"Column {column} has no numeric values"}

    counts, edges = pd.cut(series, bins=bins, retbins=True)
    hist = counts.value_counts(sort=False)

    return {
        "column": column,
        "count": int(series.count()),
        "min": _clean(series.min()),
        "max": _clean(series.max()),
        "mean": _clean(series.mean()),
        "std": _clean(series.std()),
        "bins": [
            {
                "range": f"{_clean(edges[i])}-{_clean(edges[i+1])}",
                "count": int(hist.iloc[i]),
            }
            for i in range(len(hist))
        ],
    }


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if pd.isna(v):
            return None
        return round(v, 4) if v != int(v) else int(v)
    return v
