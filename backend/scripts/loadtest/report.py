"""Writes a load run's results as the tables in docs/load-and-recovery.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

BEGIN = "<!-- results:begin -->"
END = "<!-- results:end -->"


def _value(value: Any) -> str:
    if isinstance(value, dict):
        if "p50_ms" in value:
            return (
                f"median {value['p50_ms']:g} ms, 95th percentile {value['p95_ms']:g} ms, "
                f"worst {value['max_ms']:g} ms ({value['count']} samples)"
            )
        return ", ".join(f"{key.replace('_', ' ')} {_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def results_markdown(document: dict[str, Any]) -> str:
    machine = document["machine"]
    scenarios = document["scenarios"]
    checks = [check for scenario in scenarios for check in scenario["checks"]]
    passed = sum(1 for check in checks if check["ok"])
    lines = [
        BEGIN,
        "",
        f"Run on {machine['when']} at commit `{machine['commit']}`, with "
        f"{document['students']} students.",
        "",
        f"- Machine: {machine['platform']}, {machine['cpus']} logical processors, "
        f"Python {machine['python']}.",
        "- The backend, Postgres and all the clients ran on that one machine.",
        f"- **{passed} of {len(checks)} checks passed.**",
        "",
        "| Scenario | Checks passed | Took |",
        "|---|---|---|",
    ]
    for scenario in scenarios:
        ok = sum(1 for check in scenario["checks"] if check["ok"])
        took = scenario["figures"].get("scenario_seconds", "")
        lines.append(f"| {scenario['title']} | {ok} of {len(scenario['checks'])} | {took} s |")
    for scenario in scenarios:
        lines += ["", f"### {scenario['title']}", ""]
        figures = {k: v for k, v in scenario["figures"].items() if k != "scenario_seconds"}
        if figures:
            lines += ["| Measured | Result |", "|---|---|"]
            lines += [f"| {_label(key)} | {_value(value)} |" for key, value in figures.items()]
            lines.append("")
        lines += ["| Check | Result |", "|---|---|"]
        for check in scenario["checks"]:
            result = "passed" if check["ok"] else f"**FAILED**: {check['detail']}"
            lines.append(f"| {check['name'].capitalize()} | {result} |")
        for note in scenario["notes"]:
            lines += ["", f"Note: {note}"]
    lines += ["", END]
    return "\n".join(lines)


def write_markdown(path: Path, document: dict[str, Any]) -> None:
    """Put the results between the markers in the report, leaving the
    hand-written sections around them alone. A file without the markers gets
    the results on their own."""
    results = results_markdown(document)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            before, _, rest = text.partition(BEGIN)
            _, _, after = rest.partition(END)
            path.write_text(before + results + after, encoding="utf-8", newline="\n")
            return
    path.write_text(results + "\n", encoding="utf-8", newline="\n")
