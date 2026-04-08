"""Document processing tools for Stage B"""

from pathlib import Path

from bourbon.tools import RiskLevel, ToolContext, register_tool

PDF_TO_TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to PDF file",
        },
        "page_range": {
            "type": "array",
            "description": "Optional [start, end] page range (0-indexed)",
            "items": {"type": "integer"},
        },
    },
    "required": ["file_path"],
}


def pdf_to_text(
    file_path: str,
    page_range: tuple = None,
) -> dict:
    """Extract text from PDF"""
    try:
        from pypdf import PdfReader

        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }

        reader = PdfReader(file_path)
        text_parts = []

        pages = range(len(reader.pages))
        if page_range and len(page_range) == 2:
            start, end = page_range
            pages = range(start, min(end, len(reader.pages)))

        for i in pages:
            page = reader.pages[i]
            page_text = page.extract_text()
            if page_text.strip():
                text_parts.append(f"--- Page {i + 1} ---\n")
                text_parts.append(page_text)

        return {
            "success": True,
            "file_path": file_path,
            "text": "\n".join(text_parts),
            "page_count": len(reader.pages),
            "pages_extracted": len(pages),
        }

    except ImportError:
        return {
            "success": False,
            "error": "pypdf not installed. Install with: uv pip install pypdf",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


DOCX_TO_MARKDOWN_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to Word document (.docx)",
        },
    },
    "required": ["file_path"],
}


def docx_to_markdown(
    file_path: str,
) -> dict:
    """Convert Word docx to markdown"""
    try:
        from docx import Document

        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }

        doc = Document(file_path)
        md_parts = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                # Simple heading detection based on style
                style = para.style.name if para.style else ""
                if "Heading" in style:
                    level = style.replace("Heading ", "").replace("Heading", "1")
                    try:
                        level_num = int(level)
                        md_parts.append(f"{'#' * level_num} {text}\n")
                    except ValueError:
                        md_parts.append(f"## {text}\n")
                else:
                    md_parts.append(f"{text}\n")

        return {
            "success": True,
            "file_path": file_path,
            "text": "\n".join(md_parts),
        }

    except ImportError:
        return {
            "success": False,
            "error": "python-docx not installed. Install with: uv pip install python-docx",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@register_tool(
    name="PdfRead",
    aliases=["pdf_to_text"],
    description="Extract text from PDF file.",
    input_schema=PDF_TO_TEXT_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="pdf document read extract text",
    required_capabilities=["file_read"],
)
def pdf_read_handler(
    file_path: str,
    page_range: list[int] | None = None,
    *,
    ctx: ToolContext,
) -> str:
    """Tool handler for PdfRead."""
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = pdf_to_text(resolved, page_range)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)


@register_tool(
    name="DocxRead",
    aliases=["docx_to_markdown"],
    description="Convert Word document to markdown.",
    input_schema=DOCX_TO_MARKDOWN_SCHEMA,
    risk_level=RiskLevel.LOW,
    always_load=False,
    should_defer=True,
    is_read_only=True,
    search_hint="docx word document read convert markdown",
    required_capabilities=["file_read"],
)
def docx_read_handler(file_path: str, *, ctx: ToolContext) -> str:
    """Tool handler for DocxRead."""
    resolved = str(ctx.workdir / file_path) if not Path(file_path).is_absolute() else file_path
    result = docx_to_markdown(resolved)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)
