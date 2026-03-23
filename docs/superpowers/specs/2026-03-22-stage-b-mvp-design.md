---
title: Stage B MVP - Skill-Based General Assistant
description: Expand Bourbon from code specialist to general knowledge worker using Skill system
author: bourbon
version: 1.0
date: 2026-03-22
status: approved
---

# Stage B MVP Design: Skill-Based General Assistant

> **Design approved via brainstorming skill**

## Overview

Transform Bourbon from a code specialist into a general-purpose knowledge worker by adding 4 core skills: Web Fetch, Data Analysis, Document Parse, and Report Generation.

## Architecture

```
┌─────────────────────────────────────────┐
│         Bourbon Agent (Stage B)         │
├─────────────────────────────────────────┤
│  Core Tools (Stage A)                   │
│  ├── bash, rg, ast-grep, file ops      │
│  └── read/write/edit                   │
├─────────────────────────────────────────┤
│  Stage B Skills (MVP)                   │
│  ├── web-fetch-skill/   ← URL 获取     │
│  ├── data-analysis-skill/  ← CSV/JSON  │
│  ├── document-parse-skill/ ← PDF/Word  │
│  └── report-gen-skill/     ← 报告生成  │
├─────────────────────────────────────────┤
│  Integration                            │
│  └── 工作流: skill("web-fetch") →      │
│             skill("data-analysis") →   │
│             skill("report-gen")        │
└─────────────────────────────────────────┘
```

## Skills Specification

### 1. web-fetch-skill

**Purpose**: Fetch URL content and extract text

**Capabilities**:
- HTTP GET requests with timeout
- HTML → text conversion
- JSON response handling
- Rate limiting protection

**Files**:
- `SKILL.md` - Instructions for using web fetch
- `scripts/fetch.py` - HTTP client with safety limits

**Example**:
```python
# User: "Get content from https://example.com"
# Agent uses web-fetch skill
result = skill("web-fetch", url="https://example.com")
# Returns: {title, text_content, links}
```

### 2. data-analysis-skill

**Purpose**: Analyze CSV/JSON data

**Capabilities**:
- Load CSV/JSON files
- Basic statistics (count, mean, min, max)
- Simple filtering and grouping
- ASCII chart generation

**Files**:
- `SKILL.md` - Data analysis patterns
- `scripts/analyze.py` - Pandas-based analysis

**Example**:
```python
# User: "Analyze sales.csv"
# Agent uses data-analysis skill
result = skill("data-analysis", file="sales.csv", operation="summary")
# Returns: statistics + sample data
```

### 3. document-parse-skill

**Purpose**: Extract text from PDF and Word documents

**Capabilities**:
- PDF text extraction (pypdf)
- Word docx to markdown (python-docx)
- Page range selection
- Structure preservation

**Files**:
- `SKILL.md` - Document processing guide

**Tools** (in bourbon/tools/documents.py):
- `pdf_to_text()` - Extract text from PDF
- `docx_to_markdown()` - Convert Word to markdown

**Example**:
```python
# User: "Extract text from report.pdf"
result = skill("document-parse", file="report.pdf")
# Returns: extracted text with page markers
```

### 4. report-gen-skill

**Purpose**: Generate structured reports from data

**Capabilities**:
- Markdown report generation
- Jinja2 template filling
- Data → table conversion
- Section-based structure

**Files**:
- `SKILL.md` - Report generation patterns
- `templates/report.md.j2` - Default report template

**Example**:
```python
# User: "Generate report from analysis results"
result = skill("report-gen", title="Sales Analysis", data=analysis_results)
# Returns: markdown report
```

## Integration: Mixed-Domain Workflow

### Example Workflow

**User**: "Analyze sales.csv, fetch competitor pricing from web, generate comparison report"

**Agent Workflow**:

1. **skill("data-analysis")**
   ```python
   sales_data = skill("data-analysis", 
                      file="sales.csv",
                      operations=["summary", "groupby:product", "sum:revenue"])
   ```

2. **skill("web-fetch")**
   ```python
   competitor_data = skill("web-fetch",
                           url="https://competitor.com/pricing",
                           extract="tables")
   ```

3. **skill("data-analysis")**
   ```python
   comparison = skill("data-analysis",
                      merge=[sales_data, competitor_data],
                      operation="compare")
   ```

4. **skill("report-gen")**
   ```python
   report = skill("report-gen",
                  title="Sales vs Competitor Analysis",
                  sections=[
                      {"type": "summary", "data": comparison.summary},
                      {"type": "table", "data": comparison.details},
                      {"type": "chart", "data": comparison.trends}
                  ])
   ```

**Output**: `sales_comparison_report.md`

## Tool Extensions

### src/bourbon/tools/data.py

```python
@tool(risk_level=RiskLevel.LOW)
def csv_analyze(file_path: str, operations: list) -> AnalysisResult:
    """Analyze CSV with pandas operations"""
    
@tool(risk_level=RiskLevel.LOW)
def json_query(file_path: str, query: str) -> QueryResult:
    """Query JSON with jsonpath"""
```

### src/bourbon/tools/documents.py

```python
@tool(risk_level=RiskLevel.LOW)
def pdf_to_text(file_path: str, page_range: tuple = None) -> str:
    """Extract text from PDF"""
    
@tool(risk_level=RiskLevel.LOW)
def docx_to_markdown(file_path: str) -> str:
    """Convert Word to markdown"""
```

### src/bourbon/tools/web.py

```python
@tool(risk_level=RiskLevel.MEDIUM)
def fetch_url(url: str, timeout: int = 30) -> FetchResult:
    """Fetch URL content (used by web-fetch-skill)"""
```

## File Structure

```
.kimi/skills/
├── web-fetch-skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── fetch.py
│   └── references/
│       └── http-safety.md
├── data-analysis-skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   └── analyze.py
│   └── references/
│       └── pandas-cheatsheet.md
├── document-parse-skill/
│   ├── SKILL.md
│   └── references/
│       └── supported-formats.md
└── report-gen-skill/
    ├── SKILL.md
    ├── templates/
    │   └── report.md.j2
    └── references/
        └── markdown-guide.md

src/bourbon/tools/
├── __init__.py
├── base.py
├── search.py
├── skill_tool.py
├── data.py              # NEW
├── documents.py         # NEW
└── web.py               # NEW
```

## Dependencies

```toml
[project.optional-dependencies]
stage-b = [
    "pandas>=2.0.0",
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "jinja2>=3.1.0",
    "requests>=2.31.0",
    "beautifulsoup4>=4.12.0",
]
```

## Success Criteria

### Functional
- [ ] Can fetch and extract text from 5+ websites
- [ ] Can analyze CSV with grouping and aggregation
- [ ] Can extract text from PDF and Word files
- [ ] Can generate markdown reports from data
- [ ] Can execute mixed-domain workflow end-to-end

### Performance
- [ ] Web fetch < 10s for typical pages
- [ ] CSV analysis < 3s for <100k rows
- [ ] PDF extraction < 5s for <10MB files

### Safety
- [ ] URL validation for web requests
- [ ] File size limits for uploads
- [ ] Sandboxed document extraction
- [ ] No credential exposure in logs

## Implementation Plan

See: `docs/superpowers/plans/2026-03-22-stage-b-mvp-implementation.md`

---

*Approved for implementation*
