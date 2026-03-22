---
name: web-fetch
description: Fetch content from URLs for web data extraction
version: "1.0"
author: bourbon
---

# Web Fetch Skill

Fetch content from URLs for web data extraction and analysis.

## Usage

```python
# Basic fetch
result = skill("web-fetch", url="https://example.com")

# With options
result = skill("web-fetch", 
               url="https://api.example.com/data",
               timeout=60)

# Access results
if result["success"]:
    print(f"Status: {result['status_code']}")
    print(f"Content length: {len(result['text'])}")
else:
    print(f"Error: {result['error']}")
```

## Safety

- Only `http://` and `https://` URLs allowed
- 30s default timeout (configurable)
- Max 100KB response size (truncated with notice)
- Invalid URLs return error without network call

## Examples

### Fetch API data
```python
result = skill("web-fetch", url="https://api.github.com/users/octocat")
# Returns JSON response as text
```

### Fetch with custom timeout
```python
result = skill("web-fetch", 
               url="https://slow-site.com/data",
               timeout=60)
```

### Error handling
```python
result = skill("web-fetch", url="not-a-url")
# Returns: {"success": false, "error": "Invalid URL format..."}
```

## Output Format

```python
{
    "success": bool,
    "url": str,
    "status_code": int,  # HTTP status (0 if failed before request)
    "text": str,         # Response body (truncated if >100KB)
    "error": str,        # Error message if failed
}
```
