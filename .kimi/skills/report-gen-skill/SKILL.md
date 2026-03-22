---
name: report-gen
description: Generate markdown reports from data using templates
version: "1.0"
author: bourbon
---

# Report Generation Skill

Generate structured markdown reports from data using Jinja2 templates.

## Usage

```python
# Basic report from data
result = skill("report-gen",
               title="Sales Analysis",
               data=sales_data)

# With sections
result = skill("report-gen",
               title="Quarterly Report",
               sections=[
                   {"heading": "Summary", "content": summary_text},
                   {"heading": "Data", "table": data_table},
               ])

# Save to file
result = skill("report-gen",
               title="Analysis",
               data=data,
               output_file="report.md")
```

## Parameters

- `title` (required): Report title
- `data` (optional): Dictionary of data to include
- `sections` (optional): List of section dictionaries
- `summary` (optional): Summary text for overview section
- `output_file` (optional): Save report to file path

## Section Types

```python
# Text section
{"heading": "Overview", "content": "Text content here..."}

# Table section
{
    "heading": "Results",
    "table": {
        "columns": ["Name", "Value"],
        "rows": [["A", 100], ["B", 200]]
    }
}
```

## Examples

### Simple data report
```python
data = {
    "total_sales": 50000,
    "top_product": "Widget Pro",
    "growth": "+15%"
}

result = skill("report-gen", 
               title="Monthly Sales Report",
               data=data)

# Generated report includes:
# - Title and date
# - JSON data block
```

### Multi-section report
```python
sections = [
    {
        "heading": "Executive Summary",
        "content": "Sales increased 15% this month..."
    },
    {
        "heading": "Top Products",
        "table": {
            "columns": ["Product", "Revenue"],
            "rows": [["Widget", "$50K"], ["Gadget", "$30K"]]
        }
    }
]

result = skill("report-gen",
               title="Sales Analysis",
               sections=sections)
```

## Output Format

```python
{
    "success": True,
    "title": "Report Title",
    "report": "# Report Title\n\nGenerated: 2026-03-22...",
    "file_path": "report.md"  # if output_file specified
}
```

## Template Variables

Default template supports:
- `title`: Report title
- `date`: Generation date (auto)
- `summary`: Summary text
- `sections`: List of sections
- `data`: Raw data dict

Custom templates can be placed in `templates/` directory.
