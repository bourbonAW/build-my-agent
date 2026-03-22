---
name: data-analysis
description: Analyze CSV and JSON data with statistics and grouping
version: "1.0"
author: bourbon
---

# Data Analysis Skill

Analyze CSV and JSON data files with statistics, grouping, and querying capabilities.

## Usage

```python
# CSV summary statistics
result = skill("data-analysis", 
               file="sales.csv",
               operations=["summary"])

# With grouping
result = skill("data-analysis",
               file="sales.csv", 
               operations=["summary", "groupby:category"])

# JSON query
result = skill("data-analysis",
               file="data.json",
               query="users.0.name")
```

## Operations

### CSV Operations

- `summary`: Basic statistics (count, mean, std, min, max) for numeric columns
- `groupby:<column>`: Group and count by column value
- `sample`: Include first 5 rows in result

### JSON Query

Use dot-notation for nested access:
- `users` → Get users array
- `users.0` → First user
- `users.0.name` → First user's name
- `config.database.host` → Nested property

## Examples

### Analyze sales data
```python
result = skill("data-analysis", 
               file="sales.csv",
               operations=["summary", "groupby:product"])

# Access results
print(f"Total rows: {result['row_count']}")
print(f"Revenue mean: {result['stats']['revenue']['mean']}")
print(f"By product: {result['groups']['product']}")
```

### Query JSON API response
```python
result = skill("data-analysis",
               file="api_response.json",
               query="data.users")

# result['data'] contains the queried value
```

## Output Format

### CSV Analysis Result
```python
{
    "success": True,
    "file_path": "sales.csv",
    "row_count": 1000,
    "columns": ["date", "product", "revenue"],
    "stats": {
        "revenue": {
            "count": 1000,
            "mean": 150.50,
            "std": 45.20,
            "min": 10.00,
            "max": 500.00
        }
    },
    "groups": {
        "product": {"A": 400, "B": 350, "C": 250}
    },
    "sample": [...]  # First 5 rows
}
```

### JSON Query Result
```python
{
    "success": True,
    "file_path": "data.json",
    "query": "users.0.name",
    "data": "Alice"
}
```
