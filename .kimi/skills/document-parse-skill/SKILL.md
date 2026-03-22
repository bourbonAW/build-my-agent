---
name: document-parse
description: Extract text from PDF and Word documents
version: "1.0"
author: bourbon
---

# Document Parse Skill

Extract text content from PDF and Word documents for analysis and processing.

## Usage

```python
# PDF text extraction
result = skill("document-parse",
               file="report.pdf",
               type="pdf")

# PDF with page range (first 5 pages)
result = skill("document-parse",
               file="report.pdf",
               type="pdf",
               page_range=[0, 5])

# Word to markdown
result = skill("document-parse",
               file="document.docx",
               type="docx")
```

## Supported Formats

| Format | Extension | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Full text extraction with page markers |
| Word | `.docx` | Converts to markdown with heading detection |

## Examples

### Extract full PDF
```python
result = skill("document-parse", file="annual_report.pdf", type="pdf")

if result["success"]:
    print(f"Pages: {result['page_count']}")
    print(result["text"][:1000])  # First 1000 chars
```

### Extract specific pages
```python
# Extract pages 5-10 (0-indexed)
result = skill("document-parse",
               file="document.pdf",
               type="pdf",
               page_range=[5, 10])
```

### Convert Word to markdown
```python
result = skill("document-parse", file="meeting_notes.docx", type="docx")

# result["text"] contains markdown-formatted content
```

## Output Format

```python
# PDF result
{
    "success": True,
    "file_path": "report.pdf",
    "text": "--- Page 1 ---\nContent...\n--- Page 2 ---\n...",
    "page_count": 10,
    "pages_extracted": 10
}

# Word result
{
    "success": True,
    "file_path": "document.docx",
    "text": "# Heading\n\nParagraph content..."
}
```

## Error Handling

```python
# File not found
{
    "success": False,
    "error": "File not found: missing.pdf"
}

# Missing dependency
{
    "success": False,
    "error": "pypdf not installed. Install with: uv pip install pypdf"
}
```
