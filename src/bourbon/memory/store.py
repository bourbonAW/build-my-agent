"""Memory file store — file CRUD, MEMORY.md index, grep search."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sanitize_project_key(canonical_path: Path) -> str:
    """Derive a filesystem-safe project key from canonical path.

    Algorithm:
    1. Convert path to string
    2. Slugify: replace /, \\, space with -, remove non-ASCII, lowercase
    3. Truncate slug to 64 chars
    4. Append SHA256[:8] of original path
    """
    path_str = str(canonical_path)
    # Slugify
    slug = path_str.replace("/", "-").replace("\\", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    slug = slug[:64]
    # Hash suffix
    hash_suffix = hashlib.sha256(path_str.encode()).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"
