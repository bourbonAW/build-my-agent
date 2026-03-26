"""Artifact generation for validator handoff."""

from __future__ import annotations

import json
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OutputArtifact:
    """Structured snapshot consumed by the validator."""

    case_id: str
    workdir: Path
    meta: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)

    @property
    def artifact_dir(self) -> Path:
        return self.workdir / "artifact"

    def save(self, exclude_patterns: set[str] | None = None, max_size_mb: float = 100.0) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / "meta.json").write_text(
            json.dumps(self.meta, indent=2),
            encoding="utf-8",
        )
        (self.artifact_dir / "context.json").write_text(
            json.dumps(self.context, indent=2),
            encoding="utf-8",
        )
        (self.artifact_dir / "output.json").write_text(
            json.dumps(self.output, indent=2),
            encoding="utf-8",
        )

        workspace_dir = self.artifact_dir / "workspace"
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(
            self.workdir,
            workspace_dir,
            ignore=self._make_ignore_func(exclude_patterns or {"artifact", "__pycache__"}),
        )
        self._truncate_snapshot_if_needed(
            workspace_dir=workspace_dir,
            exclude_patterns=exclude_patterns or set(),
            max_size_mb=max_size_mb,
        )
        return self.artifact_dir

    def _make_ignore_func(self, exclude_patterns: set[str]):
        def ignore(_dir: str, names: list[str]) -> list[str]:
            return [name for name in names if self._matches_pattern(name, exclude_patterns)]

        return ignore

    def _matches_pattern(self, path_str: str, patterns: set[str]) -> bool:
        for pattern in patterns:
            if pattern.startswith("*.") and path_str.endswith(pattern[1:]):
                return True
            if path_str == pattern or path_str == pattern.rstrip("/"):
                return True
        return False

    def _truncate_snapshot_if_needed(
        self,
        workspace_dir: Path,
        exclude_patterns: set[str],
        max_size_mb: float,
    ) -> None:
        total_size = 0
        candidate_files: list[tuple[Path, int]] = []
        for file_path in workspace_dir.rglob("*"):
            if not file_path.is_file():
                continue
            rel_path = str(file_path.relative_to(workspace_dir))
            if self._matches_pattern(rel_path, exclude_patterns):
                continue
            file_size = file_path.stat().st_size
            total_size += file_size
            candidate_files.append((file_path, file_size))

        if (total_size / (1024 * 1024)) <= max_size_mb:
            return

        warnings.warn(
            "Artifact snapshot exceeded max_size_mb; truncating large files.",
            stacklevel=2,
        )
        largest_files = sorted(
            candidate_files,
            key=lambda item: item[1],
            reverse=True,
        )
        for file_path, _file_size in largest_files:
            if (total_size / (1024 * 1024)) <= max_size_mb:
                break
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if len(lines) <= 1000:
                continue
            before = file_path.stat().st_size
            file_path.write_text(
                "\n".join(lines[:1000]) + "\n[TRUNCATED: snapshot exceeded size limit]\n",
                encoding="utf-8",
            )
            total_size -= before
            total_size += file_path.stat().st_size

    @classmethod
    def load(cls, artifact_dir: Path) -> OutputArtifact:
        return cls(
            case_id=json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8"))["case_id"],
            workdir=artifact_dir / "workspace",
            meta=json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8")),
            context=json.loads((artifact_dir / "context.json").read_text(encoding="utf-8")),
            output=json.loads((artifact_dir / "output.json").read_text(encoding="utf-8")),
        )


class ArtifactBuilder:
    """Convenience builder for output artifacts."""

    def __init__(self, case_id: str, workdir: Path, max_size_mb: float = 100.0):
        self.case_id = case_id
        self.workdir = workdir
        self.max_size_mb = max_size_mb
        self._meta: dict = {}
        self._context: dict = {}
        self._output: dict = {}
        self._exclude_patterns: set[str] = {"artifact", "__pycache__"}

    def set_meta(self, **kwargs) -> ArtifactBuilder:
        self._meta.update(kwargs)
        return self

    def set_context(self, **kwargs) -> ArtifactBuilder:
        self._context.update(kwargs)
        return self

    def set_output(self, **kwargs) -> ArtifactBuilder:
        self._output.update(kwargs)
        return self

    def add_exclude_patterns(self, patterns: list[str]) -> ArtifactBuilder:
        self._exclude_patterns.update(patterns)
        return self

    def build(self) -> Path:
        artifact = OutputArtifact(
            case_id=self.case_id,
            workdir=self.workdir,
            meta={"case_id": self.case_id, **self._meta},
            context=self._context,
            output=self._output,
        )
        return artifact.save(
            exclude_patterns=self._exclude_patterns,
            max_size_mb=self.max_size_mb,
        )
