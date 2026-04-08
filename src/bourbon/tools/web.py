"""Web fetching tools for Stage B"""

from urllib.parse import urlparse

import aiohttp

from bourbon.tools import RiskLevel, ToolContext, register_tool


def _is_valid_url(url: str) -> bool:
    """Validate URL format"""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


FETCH_URL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "URL to fetch (http:// or https://)",
        },
        "timeout": {
            "type": "integer",
            "description": "Request timeout in seconds",
            "default": 30,
        },
        "max_length": {
            "type": "integer",
            "description": "Maximum response length",
            "default": 100000,
        },
    },
    "required": ["url"],
}


async def fetch_url(
    url: str,
    timeout: int = 30,
    max_length: int = 100000,
) -> dict:
    """Fetch URL content with safety limits"""
    # Validate URL
    if not _is_valid_url(url):
        return {
            "success": False,
            "url": url,
            "error": "Invalid URL format. Must be http:// or https://",
        }

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp,
        ):
            text = await resp.text()
            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "\n... [truncated]"

            return {
                "success": resp.status < 400,
                "url": url,
                "status_code": resp.status,
                "text": text,
            }
    except TimeoutError:
        return {
            "success": False,
            "url": url,
            "error": f"Timeout after {timeout}s",
        }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "error": str(e),
        }


@register_tool(
    name="WebFetch",
    aliases=["fetch_url"],
    description="Fetch and extract content from a URL.",
    input_schema=FETCH_URL_SCHEMA,
    risk_level=RiskLevel.MEDIUM,
    always_load=False,
    should_defer=True,
    search_hint="web fetch url http download browser",
    required_capabilities=["net"],
)
async def web_fetch_handler(url: str, *, ctx: ToolContext) -> str:
    """Tool handler for WebFetch."""
    del ctx
    result = await fetch_url(url)
    if isinstance(result, dict) and not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    if isinstance(result, dict):
        return result.get("text", str(result))
    return str(result)
