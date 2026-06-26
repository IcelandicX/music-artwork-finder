#!/usr/bin/env python3
"""Write short user-facing run reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

REPORT_DIR = Path.home() / ".music-artwork-finder" / "reports"


def save_run_report(
    title: str,
    mode: str,
    summaries: list[str],
    failures: list[str],
    undo_group_id: str | None = None,
) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"{timestamp}-{title.casefold().replace(' ', '-')}.txt"

    lines = [
        title,
        f"Created: {datetime.now().isoformat(timespec='seconds')}",
        f"Mode: {mode}",
    ]
    if undo_group_id:
        lines.append(f"Undo group: {undo_group_id}")
    lines.extend(["", f"Fixed albums: {len(summaries)}"])
    lines.extend(f"- {summary}" for summary in summaries)
    lines.extend(["", f"Failures: {len(failures)}"])
    lines.extend(f"- {failure}" for failure in failures)
    lines.extend(
        [
            "",
            "Tips:",
            "- If a match looks wrong, run music-cache clear, then retry with music-ai --preview or music-ai --pick.",
            "- Run music-undo to restore the latest change.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
