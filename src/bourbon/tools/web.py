"""Web fetching tools for Stage B"""
import asyncio
from urllib.parse import urlparse

import aiohttp

from bourbon.tools import RiskLevel, register_tool


def _is_valid_url(url: str) -> bool:
    """Validate URL format"""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
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


@register_tool(
    name="fetch_url",
    description="Fetch content from URL",
    input_schema=FETCH_URL_SCHEMA,
    risk_level=RiskLevel.MEDIUM,
)
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
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
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
    except asyncio.TimeoutError:
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
