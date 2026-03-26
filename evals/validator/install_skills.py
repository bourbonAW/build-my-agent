"""Install project evaluator skills into Bourbon's discovery directory."""

from __future__ import annotations

import shutil
from pathlib import Path

DEFAULT_BUILTIN_DIR = Path(__file__).parent / "skills"
DEFAULT_USER_DIR = Path.home() / ".bourbon" / "skills"


def install_skills(
    builtin_dir: Path | None = None,
    user_dir: Path | None = None,
    force: bool = True,
) -> list[str]:
    """Copy project evaluator skills into the Bourbon skills directory."""

    builtin_dir = builtin_dir or DEFAULT_BUILTIN_DIR
    user_dir = user_dir or DEFAULT_USER_DIR
    user_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    for skill_dir in builtin_dir.iterdir():
        if not skill_dir.is_dir() or not skill_dir.name.startswith("eval-"):
            continue
        target = user_dir / skill_dir.name
        if target.exists() and force:
            shutil.rmtree(target)
        if not target.exists():
            shutil.copytree(skill_dir, target)
            installed.append(skill_dir.name)
    return installed


def main() -> None:
    install_skills()


if __name__ == "__main__":
    main()
