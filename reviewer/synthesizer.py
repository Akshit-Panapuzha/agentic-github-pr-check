from typing import List, Tuple

from reviewer.config import ReviewerConfig
from reviewer.models import Finding

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def deduplicate(findings: List[Finding]) -> List[Finding]:
    """Keep highest-confidence finding per (filename, line_number, agent)."""
    best: dict = {}
    for f in findings:
        key = (f.filename, f.line_number, f.agent)
        if key not in best or f.confidence > best[key].confidence:
            best[key] = f
    return list(best.values())


def sort_findings(findings: List[Finding]) -> List[Finding]:
    return sorted(
        findings,
        key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), -f.confidence),
    )


def synthesize(
    findings: List[Finding],
    config: ReviewerConfig,
) -> Tuple[List[Finding], List[Finding], int]:
    """Split into (inline, low_confidence, truncated_count)."""
    deduped = deduplicate(findings)
    sorted_all = sort_findings(deduped)

    inline = [f for f in sorted_all if f.confidence >= config.confidence_threshold]
    low_conf = [f for f in sorted_all if f.confidence < config.confidence_threshold]

    truncated = 0
    if len(inline) > config.max_comments_per_pr:
        truncated = len(inline) - config.max_comments_per_pr
        inline = inline[: config.max_comments_per_pr]

    return inline, low_conf, truncated


def build_summary_body(
    inline: List[Finding],
    low_conf: List[Finding],
    skipped_files: List[str],
    truncated_count: int,
) -> str:
    sections = ["## AI Code Review Summary\n"]

    if not inline and not low_conf:
        sections.append("No issues found.")
    else:
        by_severity: dict = {}
        for f in inline:
            by_severity.setdefault(f.severity, []).append(f)

        for severity in ["critical", "high", "medium", "low"]:
            group = by_severity.get(severity, [])
            if not group:
                continue
            sections.append(f"\n### {severity.upper()} ({len(group)})\n")
            for f in group:
                sections.append(
                    f"- **{f.title}** (`{f.filename}:{f.line_number}`) — {f.explanation}"
                )

    if truncated_count > 0:
        sections.append(
            f"\n> **{truncated_count} additional finding(s) suppressed.** "
            f"Increase `max_comments_per_pr` in `.reviewer.yaml` to see them."
        )

    if skipped_files:
        sections.append(
            f"\n> **Skipped files** (exceeded token budget or unreadable): "
            f"{', '.join(skipped_files)}"
        )

    if low_conf:
        items = "\n".join(
            f"- **{f.title}** (`{f.filename}:{f.line_number}`, "
            f"confidence: {f.confidence:.2f}) — {f.explanation}"
            for f in low_conf
        )
        sections.append(
            f"\n<details>\n<summary>Low-confidence findings ({len(low_conf)})"
            f"</summary>\n\n{items}\n\n</details>"
        )

    return "\n".join(sections)
