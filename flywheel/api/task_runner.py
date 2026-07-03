"""Thread-based background task runner with progress tracking via pipeline.json."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from api import pipeline_state as ps

_lock = threading.Lock()
_active = False


def is_busy(root: Path, project: str) -> bool:
    # `_active` is the single, process-local source of truth for "a task is
    # currently running" — it's reset to False on every process start, so a
    # crash mid-run can never leave future requests permanently locked out
    # the way a persisted-status check could (pipeline.json's task.status is
    # display-only; see reset_stale_running()).
    return _active


def run_script(python: str, scripts_dir: Path, script: str, *args: str) -> None:
    """Run a flywheel script as a subprocess; raise on non-zero exit."""
    cmd = [python, str(scripts_dir / script), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()[-2000:]
        raise RuntimeError(f"{script} failed (exit {result.returncode}):\n{stderr}")


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def start(
    fn: Callable[[], None],
    root: Path,
    project: str,
    task_type: str,
    *,
    run_id: str = "",
    total: int = 0,
) -> bool:
    """Start fn in a background daemon thread. Returns False if a task is already running."""
    global _active
    with _lock:
        if _active:
            return False
        _active = True

    ps.update_task(
        root, project,
        type=task_type,
        status="running",
        run_id=run_id,
        done=0,
        total=total,
        phase="",
        error="",
        result="",
    )

    def _wrapper() -> None:
        global _active
        try:
            fn()
        except Exception as exc:
            ps.update_task(root, project, status="error", error=str(exc)[:500])
        finally:
            with _lock:
                _active = False

    threading.Thread(target=_wrapper, daemon=True).start()
    return True


def poll_progress(
    root: Path,
    project: str,
    output_jsonl: Path,
    total: int,
    stop_event: threading.Event,
) -> None:
    """Periodically update task.done by counting lines in output_jsonl until stop_event is set."""
    last_done = -1
    while not stop_event.is_set():
        done = count_jsonl_lines(output_jsonl)
        if done != last_done:
            ps.update_task(root, project, done=done, total=total)
            last_done = done
        time.sleep(1)
