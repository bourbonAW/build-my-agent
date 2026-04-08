"""Data analysis tools for Stage B"""

import json
from pathlib import Path

from bourbon.tools import RiskLevel, ToolContext, register_tool

CSV_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to CSV file",
        },
        "operations": {
            "type": "array",
            "description": "List of operations to perform",
            "items": {"type": "string"},
            "default": ["summary"],
        },
    },
    "required": ["file_path"],
}


def csv_analyze(
    file_path: str,
    operations: list[str] = None,
) -> dict:
    """Analyze CSV file"""
    try:
        import pandas as pd

        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }

        # Read CSV
        df = pd.read_csv(file_path)

        result = {
            "success": True,
            "file_path": file_path,
            "row_count": len(df),
            "columns": list(df.columns),
            "stats": {},
            "groups": {},
            "sample": [],
            "error": "",
        }

        # Process operations
        operations = operations or ["summary"]

        for op in operations:
            if op == "summary":
                # Numeric columns stats
                numeric_cols = df.select_dtypes(include=["number"]).columns
                for col in numeric_cols:
                    stats = df[col].describe()
                    result["stats"][col] = {
                        "count": int(stats["count"]),
                        "mean": float(stats["mean"]) if not pd.isna(stats["mean"]) else None,
                        "std": float(stats["std"]) if not pd.isna(stats["std"]) else None,
                        "min": float(stats["min"]) if not pd.isna(stats["min"]) else None,
                        "max": float(stats["max"]) if not pd.isna(stats["max"]) else None,
                    }

            elif op.startswith("groupby:"):
                col = op.split(":", 1)[1]
                if col in df.columns:
                    grouped = df.groupby(col).size().to_dict()
                    result["groups"][col] = {str(k): int(v) for k, v in grouped.items()}

        # Sample data (first 5 rows, convert to serializable types)
        sample_df = df.head(5)
        result["sample"] = [
            {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
            for row in sample_df.to_dict("records")
        ]

        return result

    except ImportError:
        return {
            "success": False,
            "error": "pandas not installed. Install with: uv pip install pandas",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


JSON_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to JSON file",
        },
        "query": {
            "type": "string",
            "description": "Dot-notation query path (e.g., 'users.0.name')",
        },
    },
    "required": ["file_path"],
}


def json_query(
    file_path: str,
    query: str = None,
) -> dict:
    """Query JSON file"""
    try:
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }

        with open(file_path) as f:
            data = json.load(f)

        # Simple dot-notation query support
        if query:
            parts = query.split(".")
            for part in parts:
                if isinstance(data, dict):
                    data = data.get(part)
                elif isinstance(data, list) and part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(data):
                        data = data[idx]
                    else:
                        return {
                            "success": False,
                            "error": f"Index {idx} out of range",
                        }
                else:
                    return {
                        "success": False,
                        "error": f"Cannot navigate into {type(data).__name__}",
                    }

        return {
            "success": True,
            "file_path": file_path,
            "query": query,
            "data": data,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@register_tool(
    name="CsvAnalyze",
    aliases=["csv_analyze"],
    description="Analyze CSV file with statistics and grouping.",
    input_schema=CSV_ANALYZE_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="csv data analyze statistics spreadsheet",
    required_capabilities=["file_read"],
)
def csv_analyze_handler(
    file_path: str,
    operations: list[str] | None = None,
    *,
    ctx: ToolContext,
) -> str:
    """Tool handler for CsvAnalyze."""
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = csv_analyze(resolved, operations)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    return json.dumps(result, indent=2, default=str)


@register_tool(
    name="JsonQuery",
    aliases=["json_query"],
    description="Query JSON file with path expression.",
    input_schema=JSON_QUERY_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="json query filter jq data",
    required_capabilities=["file_read"],
)
def json_query_handler(
    file_path: str,
    query: str | None = None,
    *,
    ctx: ToolContext,
) -> str:
    """Tool handler for JsonQuery."""
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = json_query(resolved, query)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    return json.dumps(result, indent=2, default=str)
