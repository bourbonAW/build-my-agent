"""Sample recent Langfuse traces into an error-analysis pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.common import DEFAULT_ROOT, create_langfuse_client, state_root, write_json


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    data: dict[str, Any] = {}
    for name in (
        "id",
        "name",
        "input",
        "output",
        "metadata",
        "scores",
        "level",
        "status_message",
        "latency",
        "duration",
        "observations",
    ):
        if hasattr(value, name):
            data[name] = getattr(value, name)
    return data


def _fetch_recent_traces(client: object, limit: int) -> list[dict[str, Any]]:
    for method_name in ("fetch_traces", "get_traces"):
        method = getattr(client, method_name, None)
        if callable(method):
            result = method(limit=limit)
            data = getattr(result, "data", result)
            if isinstance(data, list):
                return [_as_dict(item) for item in data]

    api = getattr(client, "api", None)
    trace_api = getattr(api, "trace", None)
    list_method = getattr(trace_api, "list", None)
    if callable(list_method):
        result = list_method(limit=limit)
        data = getattr(result, "data", result)
        if isinstance(data, list):
            return [_as_dict(item) for item in data]

    raise RuntimeError(
        "Could not fetch traces from the Langfuse client. Export traces to JSON and "
        "use --from-json, or adapt _fetch_recent_traces() to the installed SDK."
    )


def _trace_text(trace: dict[str, Any]) -> str:
    return json.dumps(trace, sort_keys=True, default=str).lower()


def _score_trace(trace: dict[str, Any]) -> tuple[int, set[str]]:
    text = _trace_text(trace)
    tags: set[str] = set()
    score = 0
    if any(token in text for token in ("error", "exception", "failed", 'score": 0', "fail")):
        tags.add("failure")
        score += 4
    if any(
        token in text for token in ("bash", "sandbox", "permission", "credential", "sudo", "rm -rf")
    ):
        tags.add("high_risk_tool")
        score += 3
    observations = trace.get("observations")
    span_count = len(observations) if isinstance(observations, list) else 0
    if span_count >= 10 or any(
        token in text for token in ("round 8", "multi-turn", "long session")
    ):
        tags.add("long_multiturn")
        score += 2
    return score, tags


def _select_stratified(traces: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    tagged: list[tuple[int, set[str], dict[str, Any]]] = []
    for trace in traces:
        score, tags = _score_trace(trace)
        tagged.append((score, tags, trace))
    buckets = {
        name: [trace for score, tags, trace in tagged if name in tags and score > 0]
        for name in ("failure", "high_risk_tool", "long_multiturn")
    }
    for name in buckets:
        buckets[name].sort(key=lambda trace: _score_trace(trace)[0], reverse=True)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(selected) < limit and any(buckets.values()):
        for name in ("failure", "high_risk_tool", "long_multiturn"):
            bucket = buckets[name]
            while bucket:
                trace = bucket.pop(0)
                trace_id = str(trace.get("id", ""))
                if trace_id and trace_id not in seen:
                    selected.append(trace)
                    seen.add(trace_id)
                    break
            if len(selected) >= limit:
                break

    fallback = sorted(
        (item for item in tagged if str(item[2].get("id", "")) not in seen),
        key=lambda item: item[0],
        reverse=True,
    )
    for _, _, trace in fallback:
        if len(selected) >= limit:
            break
        selected.append(trace)
    return selected


def _write_langfuse_dataset(
    client: object, dataset_name: str, traces: list[dict[str, Any]]
) -> None:
    create_item = getattr(client, "create_dataset_item", None)
    if not callable(create_item):
        raise RuntimeError(
            "Langfuse client does not expose create_dataset_item(); local sample file was written, "
            "but dataset creation needs an SDK adapter."
        )
    for trace in traces:
        trace_id = str(trace.get("id", ""))
        create_item(
            dataset_name=dataset_name,
            input={"trace_id": trace_id, "trace": trace.get("input", "")},
            expected_output="manual annotation required",
            metadata={"source_trace_id": trace_id, "flywheel_pool": "error_analysis"},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="bourbon")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dataset", required=True, help="Langfuse dataset/pool name to write")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--fetch-limit", type=int, default=200)
    parser.add_argument("--from-json", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.from_json is not None:
        payload = json.loads(args.from_json.read_text())
        traces = payload["traces"] if isinstance(payload, dict) and "traces" in payload else payload
        if not isinstance(traces, list):
            raise SystemExit("--from-json must contain a list or {'traces': [...]}")
        recent = [dict(trace) for trace in traces]
        client = None
    else:
        client = create_langfuse_client()
        recent = _fetch_recent_traces(client, args.fetch_limit)

    selected = _select_stratified(recent, args.limit)
    path = state_root(args.root, args.project) / "sample_traces.json"
    write_json(path, {"dataset": args.dataset, "traces": selected})

    if not args.dry_run and client is not None:
        _write_langfuse_dataset(client, args.dataset, selected)

    print(
        json.dumps(
            {
                "selected": len(selected),
                "localMirror": str(path),
                "langfuseWrite": bool(not args.dry_run and client is not None),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
