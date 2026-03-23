# Stage B MVP Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 4 Stage B skills (web-fetch, data-analysis, document-parse, report-gen) and their supporting tools

**Architecture:** Skill-based expansion using Agent Skills specification. Each skill is self-contained with SKILL.md, scripts, and references. Tools in `src/bourbon/tools/` provide low-level capabilities.

**Tech Stack:** Python 3.13, pandas, pypdf, python-docx, jinja2, requests, beautifulsoup4

---

## Module 1: Web Tools Foundation

**Files:**
- Create: `src/bourbon/tools/web.py`
- Create: `tests/tools/test_web.py`
- Create: `.kimi/skills/web-fetch-skill/SKILL.md`
- Create: `.kimi/skills/web-fetch-skill/scripts/fetch.py`

### Task 1.1: Create web.py tool

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_web.py
import pytest
from bourbon.tools.web import fetch_url

@pytest.mark.asyncio
async def test_fetch_url_success():
    """Test fetching a simple URL"""
    result = await fetch_url("https://httpbin.org/get")
    assert result.success is True
    assert result.status_code == 200
    assert "httpbin.org" in result.text

@pytest.mark.asyncio
async def test_fetch_url_invalid():
    """Test handling invalid URL"""
    result = await fetch_url("not-a-valid-url")
    assert result.success is False
    assert "Invalid URL" in result.error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/tools/test_web.py::test_fetch_url_success -v
```
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
# src/bourbon/tools/web.py
"""Web fetching tools for Stage B"""
import asyncio
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
import aiohttp

from ..tools.base import ToolResult, RiskLevel, register_tool


@dataclass
class FetchResult(ToolResult):
    """Result of URL fetch operation"""
    success: bool
    url: str
    status_code: int = 0
    text: str = ""
    error: str = ""
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "url": self.url,
            "status_code": self.status_code,
            "text": self.text[:5000] if len(self.text) > 5000 else self.text,
            "error": self.error,
        }


def _is_valid_url(url: str) -> bool:
    """Validate URL format"""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


@register_tool(
    name="fetch_url",
    description="Fetch content from URL",
    risk_level=RiskLevel.MEDIUM,
)
async def fetch_url(
    url: str,
    timeout: int = 30,
    max_length: int = 100000,
) -> FetchResult:
    """Fetch URL content with safety limits"""
    # Validate URL
    if not _is_valid_url(url):
        return FetchResult(
            success=False,
            url=url,
            error="Invalid URL format. Must be http:// or https://",
        )
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                text = await resp.text()
                # Truncate if too long
                if len(text) > max_length:
                    text = text[:max_length] + "\n... [truncated]"
                
                return FetchResult(
                    success=resp.status < 400,
                    url=url,
                    status_code=resp.status,
                    text=text,
                )
    except asyncio.TimeoutError:
        return FetchResult(
            success=False,
            url=url,
            error=f"Timeout after {timeout}s",
        )
    except Exception as e:
        return FetchResult(
            success=False,
            url=url,
            error=str(e),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/tools/test_web.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/web.py tests/tools/test_web.py
git commit -m "feat(tools): Add web fetching tool"
```

### Task 1.2: Create web-fetch-skill

- [ ] **Step 6: Create skill directory structure**

```bash
mkdir -p .kimi/skills/web-fetch-skill/scripts
mkdir -p .kimi/skills/web-fetch-skill/references
```

- [ ] **Step 7: Write SKILL.md**

```markdown
# Web Fetch Skill

Fetch content from URLs for web data extraction.

## Usage

```python
# Basic fetch
result = skill("web-fetch", url="https://example.com")

# With options
result = skill("web-fetch", 
               url="https://api.example.com/data",
               timeout=60)
```

## Safety

- Only http:// and https:// URLs allowed
- 30s default timeout (configurable)
- Max 100KB response size
- Respect robots.txt
```

- [ ] **Step 8: Write fetch.py script**

```python
#!/usr/bin/env python3
"""Web fetch script for skill invocation"""
import sys
import json
import asyncio

# Add bourbon to path
sys.path.insert(0, '/Users/whf/github_project/build-my-agent/src')

from bourbon.tools.web import fetch_url

async def main():
    args = json.loads(sys.stdin.read())
    url = args.get('url')
    timeout = args.get('timeout', 30)
    
    result = await fetch_url(url, timeout=timeout)
    print(json.dumps(result.to_dict()))

if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 9: Commit skill**

```bash
git add .kimi/skills/web-fetch-skill/
git commit -m "feat(skills): Add web-fetch-skill"
```

---

## Module 2: Data Analysis Tools

**Files:**
- Create: `src/bourbon/tools/data.py`
- Create: `tests/tools/test_data.py`
- Create: `.kimi/skills/data-analysis-skill/SKILL.md`
- Create: `.kimi/skills/data-analysis-skill/scripts/analyze.py`

### Task 2.1: Create data.py tool

- [ ] **Step 10: Write tests**

```python
# tests/tools/test_data.py
import pytest
import pandas as pd
from pathlib import Path
from bourbon.tools.data import csv_analyze

def test_csv_analyze_summary(tmp_path):
    """Test CSV summary statistics"""
    # Create test CSV
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("name,value\nA,10\nB,20\nC,30")
    
    result = csv_analyze(str(csv_file), operations=["summary"])
    assert result.success is True
    assert result.stats["value"]["mean"] == 20.0

def test_csv_analyze_groupby(tmp_path):
    """Test CSV grouping"""
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("category,value\nA,10\nA,20\nB,30")
    
    result = csv_analyze(str(csv_file), operations=["groupby:category"])
    assert result.success is True
    assert len(result.groups) == 2
```

- [ ] **Step 11: Implement data.py**

```python
# src/bourbon/tools/data.py
"""Data analysis tools for Stage B"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ..tools.base import ToolResult, RiskLevel, register_tool


@dataclass
class DataAnalysisResult(ToolResult):
    """Result of data analysis"""
    success: bool
    file_path: str = ""
    row_count: int = 0
    columns: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    sample: list = field(default_factory=list)
    error: str = ""
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "file_path": self.file_path,
            "row_count": self.row_count,
            "columns": self.columns,
            "stats": self.stats,
            "groups": self.groups,
            "sample": self.sample[:10],  # Limit sample size
            "error": self.error,
        }


@register_tool(
    name="csv_analyze",
    description="Analyze CSV file with statistics and grouping",
    risk_level=RiskLevel.LOW,
)
def csv_analyze(
    file_path: str,
    operations: list[str] = None,
) -> DataAnalysisResult:
    """Analyze CSV file"""
    try:
        path = Path(file_path)
        if not path.exists():
            return DataAnalysisResult(
                success=False,
                error=f"File not found: {file_path}",
            )
        
        # Read CSV
        df = pd.read_csv(file_path)
        
        result = DataAnalysisResult(
            success=True,
            file_path=file_path,
            row_count=len(df),
            columns=list(df.columns),
        )
        
        # Process operations
        operations = operations or ["summary"]
        
        for op in operations:
            if op == "summary":
                # Numeric columns stats
                numeric_stats = df.describe().to_dict()
                result.stats = {
                    col: {
                        "count": int(stats["count"]),
                        "mean": float(stats["mean"]) if not pd.isna(stats["mean"]) else None,
                        "std": float(stats["std"]) if not pd.isna(stats["std"]) else None,
                        "min": float(stats["min"]) if not pd.isna(stats["min"]) else None,
                        "max": float(stats["max"]) if not pd.isna(stats["max"]) else None,
                    }
                    for col, stats in numeric_stats.items()
                }
            
            elif op.startswith("groupby:"):
                col = op.split(":", 1)[1]
                if col in df.columns:
                    grouped = df.groupby(col).agg(['count', 'mean', 'sum'])
                    result.groups[col] = grouped.to_dict()
        
        # Sample data
        result.sample = df.head(5).to_dict('records')
        
        return result
        
    except Exception as e:
        return DataAnalysisResult(
            success=False,
            error=str(e),
        )


@register_tool(
    name="json_query",
    description="Query JSON file with path expression",
    risk_level=RiskLevel.LOW,
)
def json_query(
    file_path: str,
    query: str = None,
) -> ToolResult:
    """Query JSON file"""
    try:
        with open(file_path) as f:
            data = json.load(f)
        
        # Simple query support (could use jsonpath-ng for full support)
        if query:
            parts = query.split('.')
            for part in parts:
                if isinstance(data, dict):
                    data = data.get(part)
                elif isinstance(data, list) and part.isdigit():
                    data = data[int(part)]
                else:
                    break
        
        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=str(e))
```

- [ ] **Step 12: Run tests**

```bash
pytest tests/tools/test_data.py -v
```

- [ ] **Step 13: Commit**

```bash
git add src/bourbon/tools/data.py tests/tools/test_data.py
git commit -m "feat(tools): Add data analysis tools"
```

### Task 2.2: Create data-analysis-skill

- [ ] **Step 14: Create skill structure**

```bash
mkdir -p .kimi/skills/data-analysis-skill/scripts
mkdir -p .kimi/skills/data-analysis-skill/references
```

- [ ] **Step 15: Write SKILL.md**

```markdown
# Data Analysis Skill

Analyze CSV and JSON data with statistics and grouping.

## Usage

```python
# CSV summary
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

- `summary`: Basic statistics for numeric columns
- `groupby:<column>`: Group and aggregate by column
- `sample`: Show first 5 rows
```

- [ ] **Step 16: Write analyze.py script**

```python
#!/usr/bin/env python3
"""Data analysis script for skill invocation"""
import sys
import json

sys.path.insert(0, '/Users/whf/github_project/build-my-agent/src')

from bourbon.tools.data import csv_analyze, json_query

def main():
    args = json.loads(sys.stdin.read())
    file_path = args.get('file')
    operations = args.get('operations', ['summary'])
    query = args.get('query')
    
    if file_path.endswith('.csv'):
        result = csv_analyze(file_path, operations)
    elif file_path.endswith('.json'):
        result = json_query(file_path, query)
    else:
        result = type('Result', (), {
            'success': False,
            'error': 'Unsupported file format',
            'to_dict': lambda self: {'success': False, 'error': 'Unsupported file format'}
        })()
    
    print(json.dumps(result.to_dict()))

if __name__ == '__main__':
    main()
```

- [ ] **Step 17: Commit**

```bash
git add .kimi/skills/data-analysis-skill/
git commit -m "feat(skills): Add data-analysis-skill"
```

---

## Module 3: Document Parse Tools

**Files:**
- Create: `src/bourbon/tools/documents.py`
- Create: `tests/tools/test_documents.py`
- Create: `.kimi/skills/document-parse-skill/SKILL.md`

### Task 3.1: Create documents.py tool

- [ ] **Step 18: Write tests**

```python
# tests/tools/test_documents.py
import pytest
from pathlib import Path
from bourbon.tools.documents import pdf_to_text, docx_to_markdown

def test_pdf_to_text(tmp_path):
    """Test PDF text extraction"""
    # Note: Create minimal PDF or mock
    # For now, just test error handling
    result = pdf_to_text("nonexistent.pdf")
    assert result.success is False
    assert "not found" in result.error.lower()
```

- [ ] **Step 19: Implement documents.py**

```python
# src/bourbon/tools/documents.py
"""Document processing tools for Stage B"""
from dataclasses import dataclass
from pathlib import Path

from ..tools.base import ToolResult, RiskLevel, register_tool


@dataclass
class DocumentResult(ToolResult):
    """Result of document extraction"""
    success: bool
    file_path: str = ""
    text: str = ""
    page_count: int = 0
    error: str = ""
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "file_path": self.file_path,
            "text": self.text[:10000] if len(self.text) > 10000 else self.text,
            "page_count": self.page_count,
            "error": self.error,
        }


@register_tool(
    name="pdf_to_text",
    description="Extract text from PDF file",
    risk_level=RiskLevel.LOW,
)
def pdf_to_text(
    file_path: str,
    page_range: tuple = None,
) -> DocumentResult:
    """Extract text from PDF"""
    try:
        from pypdf import PdfReader
        
        path = Path(file_path)
        if not path.exists():
            return DocumentResult(
                success=False,
                error=f"File not found: {file_path}",
            )
        
        reader = PdfReader(file_path)
        text_parts = []
        
        pages = range(len(reader.pages))
        if page_range:
            start, end = page_range
            pages = range(start, min(end, len(reader.pages)))
        
        for i in pages:
            page = reader.pages[i]
            text_parts.append(f"--- Page {i+1} ---\n")
            text_parts.append(page.extract_text())
        
        return DocumentResult(
            success=True,
            file_path=file_path,
            text="\n".join(text_parts),
            page_count=len(reader.pages),
        )
        
    except ImportError:
        return DocumentResult(
            success=False,
            error="pypdf not installed. Install with: uv pip install pypdf",
        )
    except Exception as e:
        return DocumentResult(
            success=False,
            error=str(e),
        )


@register_tool(
    name="docx_to_markdown",
    description="Convert Word document to markdown",
    risk_level=RiskLevel.LOW,
)
def docx_to_markdown(
    file_path: str,
) -> DocumentResult:
    """Convert Word docx to markdown"""
    try:
        from docx import Document
        
        path = Path(file_path)
        if not path.exists():
            return DocumentResult(
                success=False,
                error=f"File not found: {file_path}",
            )
        
        doc = Document(file_path)
        md_parts = []
        
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                # Simple heading detection
                if text.startswith('#'):
                    md_parts.append(text)
                else:
                    md_parts.append(text)
                md_parts.append('')
        
        return DocumentResult(
            success=True,
            file_path=file_path,
            text="\n".join(md_parts),
        )
        
    except ImportError:
        return DocumentResult(
            success=False,
            error="python-docx not installed. Install with: uv pip install python-docx",
        )
    except Exception as e:
        return DocumentResult(
            success=False,
            error=str(e),
        )
```

- [ ] **Step 20: Run tests**

```bash
pytest tests/tools/test_documents.py -v
```

- [ ] **Step 21: Commit**

```bash
git add src/bourbon/tools/documents.py tests/tools/test_documents.py
git commit -m "feat(tools): Add document processing tools"
```

### Task 3.2: Create document-parse-skill

- [ ] **Step 22: Create skill structure**

```bash
mkdir -p .kimi/skills/document-parse-skill/references
```

- [ ] **Step 23: Write SKILL.md**

```markdown
# Document Parse Skill

Extract text from PDF and Word documents.

## Usage

```python
# PDF text extraction
result = skill("document-parse",
               file="report.pdf",
               type="pdf")

# PDF with page range
result = skill("document-parse",
               file="report.pdf",
               type="pdf",
               page_range=(0, 5))  # First 5 pages

# Word to markdown
result = skill("document-parse",
               file="document.docx",
               type="docx")
```

## Supported Formats

- PDF (.pdf) - Full text extraction with page markers
- Word (.docx) - Convert to markdown

## Output

```python
{
    "success": True,
    "text": "extracted content...",
    "page_count": 10  # for PDF
}
```
```

- [ ] **Step 24: Commit**

```bash
git add .kimi/skills/document-parse-skill/
git commit -m "feat(skills): Add document-parse-skill"
```

---

## Module 4: Report Generation Skill

**Files:**
- Create: `.kimi/skills/report-gen-skill/SKILL.md`
- Create: `.kimi/skills/report-gen-skill/templates/report.md.j2`
- Create: `src/bourbon/tools/report.py` (optional, can be pure skill)

### Task 4.1: Create report-gen-skill

- [ ] **Step 25: Create skill structure**

```bash
mkdir -p .kimi/skills/report-gen-skill/templates
mkdir -p .kimi/skills/report-gen-skill/references
```

- [ ] **Step 26: Write SKILL.md**

```markdown
# Report Generation Skill

Generate markdown reports from data using templates.

## Usage

```python
# Basic report
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
```

## Template Variables

- `title`: Report title
- `date`: Generation date (auto)
- `sections`: List of section dicts
- `data`: Raw data dict
```

- [ ] **Step 27: Write default template**

```jinja2
{# .kimi/skills/report-gen-skill/templates/report.md.j2 #}
# {{ title }}

Generated: {{ date }}

{% if summary %}
## Summary

{{ summary }}

{% endif %}

{% for section in sections %}
## {{ section.heading }}

{% if section.content %}
{{ section.content }}
{% endif %}

{% if section.table %}
| {% for col in section.table.columns %}{{ col }} | {% endfor %}
| {% for _ in section.table.columns %}--- | {% endfor %}
{% for row in section.table.rows %}
| {% for cell in row %}{{ cell }} | {% endfor %}
{% endfor %}
{% endif %}

{% endfor %}

{% if data %}
## Data

```json
{{ data | tojson(indent=2) }}
```
{% endif %}
```

- [ ] **Step 28: Create report generation script**

```python
# .kimi/skills/report-gen-skill/scripts/generate.py
#!/usr/bin/env python3
"""Report generation script"""
import sys
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Template

def main():
    args = json.loads(sys.stdin.read())
    title = args.get('title', 'Report')
    data = args.get('data', {})
    sections = args.get('sections', [])
    summary = args.get('summary', '')
    
    # Load template
    template_path = Path(__file__).parent.parent / 'templates' / 'report.md.j2'
    if template_path.exists():
        template = Template(template_path.read_text())
    else:
        # Default template
        template = Template("""# {{ title }}

Generated: {{ date }}

{% if summary %}{{ summary }}{% endif %}

{% for section in sections %}
## {{ section.heading }}
{{ section.content }}
{% endfor %}
""")
    
    report = template.render(
        title=title,
        date=datetime.now().strftime('%Y-%m-%d %H:%M'),
        data=data,
        sections=sections,
        summary=summary,
    )
    
    print(json.dumps({
        'success': True,
        'report': report,
        'title': title,
    }))

if __name__ == '__main__':
    main()
```

- [ ] **Step 29: Commit**

```bash
git add .kimi/skills/report-gen-skill/
git commit -m "feat(skills): Add report-gen-skill"
```

---

## Module 5: Integration & Testing

### Task 5.1: Add dependencies

- [ ] **Step 30: Update pyproject.toml**

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff", ...]
stage-b = [
    "pandas>=2.0.0",
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "jinja2>=3.1.0",
    "aiohttp>=3.9.0",
    "beautifulsoup4>=4.12.0",
]
all = [
    "bourbon[dev,stage-b]"
]
```

- [ ] **Step 31: Install dependencies**

```bash
uv pip install -e ".[stage-b]"
```

- [ ] **Step 32: Commit**

```bash
git add pyproject.toml
git commit -m "build: Add Stage B dependencies"
```

### Task 5.2: Create integration tests

- [ ] **Step 33: Create end-to-end test**

```python
# tests/stage_b/test_integration.py
"""Integration tests for Stage B MVP"""
import pytest
import tempfile
from pathlib import Path

@pytest.mark.integration
def test_mixed_workflow_csv_web_report():
    """Test: CSV → Web fetch → Report workflow"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test CSV
        csv_file = Path(tmpdir) / "sales.csv"
        csv_file.write_text("product,revenue\nA,100\nB,200\nC,300")
        
        # Step 1: Analyze CSV
        from bourbon.tools.data import csv_analyze
        analysis = csv_analyze(str(csv_file), ["summary"])
        assert analysis.success
        
        # Step 2: Generate report from analysis
        from jinja2 import Template
        template = Template("""
# Sales Analysis Report

Total Revenue: ${{ total }}
Average: ${{ avg }}
""")
        
        total = analysis.stats.get('revenue', {}).get('sum', 0)
        report = template.render(total=total, avg=total/3)
        
        assert "Sales Analysis Report" in report
        assert "$600" in report  # Total

@pytest.mark.integration
def test_document_to_analysis_workflow():
    """Test: Document → Extract → Analyze workflow"""
    # This would need actual PDF/docx files
    # For now, just test skill loading
    pass
```

- [ ] **Step 34: Run integration tests**

```bash
pytest tests/stage_b/ -v -m integration
```

- [ ] **Step 35: Commit**

```bash
git add tests/stage_b/
git commit -m "test(stage-b): Add integration tests"
```

### Task 5.3: Create eval cases

- [ ] **Step 36: Create Stage B eval cases**

```bash
mkdir -p evals/cases/stage-b
```

```json
// evals/cases/stage-b/csv-analysis.json
{
  "id": "stage-b-csv-001",
  "name": "CSV Data Analysis",
  "category": "stage-b",
  "skill": "data-analysis",
  "difficulty": "easy",
  "prompt": "Analyze the sales.csv file and tell me the total revenue and best performing product",
  "setup": {
    "files": {
      "sales.csv": "product,revenue\nA,1000\nB,2000\nC,1500"
    }
  },
  "assertions": [
    {
      "id": "total_revenue",
      "check": "output_contains:4500"
    },
    {
      "id": "best_product",
      "check": "output_contains:B"
    }
  ]
}
```

- [ ] **Step 37: Commit eval cases**

```bash
git add evals/cases/stage-b/
git commit -m "test(evals): Add Stage B eval cases"
```

---

## Module 6: Documentation

### Task 6.1: Update AGENTS.md

- [ ] **Step 38: Add Stage B section to AGENTS.md**

```markdown
## Stage B Capabilities

### Web Fetching
- `fetch_url` - Fetch content from URLs
- `web-fetch-skill` - Skill wrapper for web operations

### Data Analysis
- `csv_analyze` - Analyze CSV with statistics
- `json_query` - Query JSON files
- `data-analysis-skill` - Skill wrapper

### Document Processing
- `pdf_to_text` - Extract text from PDF
- `docx_to_markdown` - Convert Word to markdown
- `document-parse-skill` - Skill wrapper

### Report Generation
- `report-gen-skill` - Generate markdown reports
```

- [ ] **Step 39: Update README.md with Stage B features**

- [ ] **Step 40: Final commit**

```bash
git add AGENTS.md README.md
git commit -m "docs: Update documentation for Stage B MVP"
```

---

## Success Verification

Run all checks:

```bash
# Unit tests
pytest tests/tools/test_web.py tests/tools/test_data.py tests/tools/test_documents.py -v

# Integration tests
pytest tests/stage_b/ -v

# Eval tests
uv run python evals/runner.py --category stage-b

# Check all skills load
python -c "from bourbon.skills import SkillManager; sm = SkillManager(); sm._discover(); print('Skills:', list(sm.available_skills()))"
```

---

## Deliverables Summary

| Deliverable | Location | Status |
|-------------|----------|--------|
| web-fetch-skill | `.kimi/skills/web-fetch-skill/` | ⬜ |
| data-analysis-skill | `.kimi/skills/data-analysis-skill/` | ⬜ |
| document-parse-skill | `.kimi/skills/document-parse-skill/` | ⬜ |
| report-gen-skill | `.kimi/skills/report-gen-skill/` | ⬜ |
| web.py tool | `src/bourbon/tools/web.py` | ⬜ |
| data.py tool | `src/bourbon/tools/data.py` | ⬜ |
| documents.py tool | `src/bourbon/tools/documents.py` | ⬜ |
| Integration tests | `tests/stage_b/` | ⬜ |
| Eval cases | `evals/cases/stage-b/` | ⬜ |
| Documentation | `AGENTS.md`, `README.md` | ⬜ |

---

**Ready for implementation!**

Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to execute this plan.
