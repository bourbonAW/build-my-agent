"""Promptfoo provider for pre-built artifact evaluation (calibration cases).

Returns fixture code content as output for promptfoo's llm-rubric to judge.
Does NOT run the Bourbon agent.
"""

from pathlib import Path


def call_api(prompt, options, context):
    """Return pre-built artifact content for LLM judging.

    Expects vars.fixture to name a fixture directory under evals/fixtures/.
    Reads all files from artifact/workspace/ and returns concatenated code as
    a plain string — no JSON wrapping. This keeps llm-rubric input clean.
    """
    config = options.get("config", {})
    vars_ = config.get("vars", {}) if "vars" not in options else options.get("vars", {})
    if not vars_:
        vars_ = options.get("vars", {})

    fixture = vars_.get("fixture", "")
    if not fixture:
        return {"error": "No fixture specified in vars.fixture"}

    evals_dir = Path(__file__).parent
    fixture_dir = evals_dir / "fixtures" / fixture

    if not fixture_dir.exists():
        return {"error": f"Fixture directory not found: {fixture_dir}"}

    workspace_dir = fixture_dir / "artifact" / "workspace"
    if not workspace_dir.exists():
        return {"error": f"No artifact/workspace/ in fixture: {fixture}"}

    parts = []
    for f in sorted(workspace_dir.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(workspace_dir))
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = f"<binary file, {f.stat().st_size} bytes>"
            parts.append(f"--- {rel} ---\n{content}")

    return {"output": "\n\n".join(parts)}
