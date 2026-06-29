"""Thin read-only API serving report JSON + Langfuse run summaries (UI §4, §8)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException

from flywheel.report import _safe_segment, read_json


def _contained_path(base: Path, name: str) -> Path | None:
    try:
        _safe_segment(name)
    except ValueError:
        return None
    resolved_base = base.resolve()
    path = (resolved_base / f"{name}.json").resolve()
    return path if path.parent == resolved_base else None


def create_app(
    root: Path,
    *,
    project: str,
    runs_provider: Callable[[str], list[dict[str, object]]],
) -> FastAPI:
    app = FastAPI(title="Flywheel Read API")
    root = Path(root)
    project = _safe_segment(project)

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, object]]:
        return runs_provider(project)

    def report_path(kind: str, name: str) -> Path | None:
        path = _contained_path(root / project / "reports" / kind, name)
        return path if path is not None and path.exists() else None

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        path = report_path("regression", run_id)
        if path is None:
            raise HTTPException(status_code=404, detail="regression report not found")
        return read_json(path)

    @app.get("/api/judges/{judge_version}")
    def get_judge(judge_version: str) -> dict[str, object]:
        path = report_path("judge", judge_version)
        if path is None:
            raise HTTPException(status_code=404, detail="judge report not found")
        return read_json(path)

    return app
