"""Runnable ASGI entrypoint — wires read API + pipeline router.

Env:
  FLYWHEEL_ROOT             report/state root (default ~/.flywheel)
  FLYWHEEL_PROJECT          project name (default "bourbon")
  FLYWHEEL_HOST / _PORT     bind address (default 127.0.0.1:8000)
  LANGFUSE_PUBLIC_KEY       Langfuse credentials (optional; pipeline degrades without)
  LANGFUSE_SECRET_KEY
  LANGFUSE_HOST             Langfuse base URL (default https://cloud.langfuse.com)
  FLYWHEEL_JUDGE_VERSION    default judge-v1
  FLYWHEEL_JUDGE_MODEL      default claude-sonnet-4-6
  FLYWHEEL_JUDGE_PROMPT_VERSION  default p1
  FLYWHEEL_HARNESS_MODEL    default = FLYWHEEL_JUDGE_MODEL
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI

from api import pipeline_state as ps
from api.pipeline import configure as configure_pipeline
from api.pipeline import router as pipeline_router
from api.read_api import create_app
from api.runs_provider import list_runs

_FLYWHEEL_DIR = Path(__file__).resolve().parents[1]


def _root() -> Path:
    return Path(os.environ.get("FLYWHEEL_ROOT", "~/.flywheel")).expanduser()


def _python() -> str:
    return sys.executable


def _make_langfuse() -> object | None:
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))
    if not pub or not sec:
        return None
    try:
        try:
            from langfuse import Langfuse
            return Langfuse(public_key=pub, secret_key=sec, host=host)
        except ImportError:
            return None
    except Exception:
        return None


def build_app() -> FastAPI:
    root = _root()
    project = os.environ.get("FLYWHEEL_PROJECT", "bourbon")
    langfuse = _make_langfuse()

    # Ensure scripts/ is importable
    scripts_parent = str(_FLYWHEEL_DIR)
    if scripts_parent not in sys.path:
        sys.path.insert(0, scripts_parent)

    configure_pipeline(root, project, langfuse=langfuse, python=_python())
    ps.reset_stale_running(root, project)

    def runs_provider(proj: str) -> list[dict[str, object]]:
        return list_runs(root, proj, langfuse=langfuse)

    app = create_app(root, project=project, runs_provider=runs_provider)
    app.include_router(pipeline_router)
    return app


app = build_app()


def main() -> None:
    import uvicorn
    host = os.environ.get("FLYWHEEL_HOST", "127.0.0.1")
    port = int(os.environ.get("FLYWHEEL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
