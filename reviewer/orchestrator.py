import asyncio
import os
from typing import List, Tuple

from github import Github
from openai import AsyncOpenAI

from reviewer.agents.critique import run_critique_agent
from reviewer.agents.quality import run_quality_agent
from reviewer.agents.security import run_security_agent
from reviewer.config import ReviewerConfig
from reviewer.embeddings import chunk_file_content, rank_chunks_by_relevance
from reviewer.github_client import should_skip_file
from reviewer.models import Finding


def compute_complexity(source: str) -> str:
    try:
        from radon.complexity import cc_visit
        results = cc_visit(source)
        if not results:
            return "Cyclomatic complexity: N/A"
        lines = [f"  {r.name}: {r.complexity}" for r in sorted(results, key=lambda r: -r.complexity)]
        return "Cyclomatic complexity scores:\n" + "\n".join(lines)
    except Exception:
        return "Cyclomatic complexity: could not compute"


async def build_file_context(
    client: AsyncOpenAI,
    filename: str,
    patch: str,
    file_content: str,
    config: ReviewerConfig,
) -> str | None:
    added_lines_text = "\n".join(
        line[1:] for line in patch.split("\n")
        if line.startswith("+") and not line.startswith("+++")
    )
    if not added_lines_text.strip():
        return None

    estimated_tokens = len(file_content) // 4
    if estimated_tokens <= config.token_budget_per_file:
        return file_content

    chunks = chunk_file_content(file_content)
    relevant = await rank_chunks_by_relevance(
        client, added_lines_text, chunks, token_budget=config.token_budget_per_file
    )
    return "\n".join(relevant) if relevant else None


async def _analyze_file(
    client: AsyncOpenAI,
    filename: str,
    patch: str,
    file_content: str,
    config: ReviewerConfig,
    skipped: list,
) -> List[Finding]:
    context = await build_file_context(client, filename, patch, file_content, config)
    if context is None:
        skipped.append(filename)
        return []

    complexity_summary = compute_complexity(file_content)

    quality_task = run_quality_agent(client, filename, context, complexity_summary, config)
    security_task = run_security_agent(client, filename, context, patch, config)

    results = await asyncio.gather(quality_task, security_task, return_exceptions=True)

    findings = []
    for result in results:
        if not isinstance(result, Exception):
            findings.extend(result)
    return findings


async def run_pipeline(
    pr_number: int,
    repo_name: str,
    base_sha: str,
    head_sha: str,
    config: ReviewerConfig,
) -> Tuple[List[Finding], List[str]]:
    g = Github(os.environ["GITHUB_TOKEN"])
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    skipped_files: List[str] = []
    file_tasks = []

    pr_files = list(pr.get_files())

    for f in pr_files:
        if should_skip_file(f.filename, config):
            continue
        try:
            file_content = repo.get_contents(f.filename, ref=head_sha).decoded_content.decode("utf-8")
        except Exception:
            skipped_files.append(f.filename)
            continue

        file_tasks.append(
            _analyze_file(client, f.filename, f.patch or "", file_content, config, skipped_files)
        )

    results = await asyncio.gather(*file_tasks, return_exceptions=True)

    all_findings: List[Finding] = []
    for result in results:
        if not isinstance(result, Exception):
            all_findings.extend(result)

    all_findings = [f for f in all_findings if f.severity in config.severity_filter]

    # Critique loop with re-run cap
    reruns = 0
    while True:
        all_findings = await run_critique_agent(client, all_findings, config)

        if not all_findings:
            break

        avg_confidence = sum(f.confidence for f in all_findings) / len(all_findings)
        if avg_confidence >= config.rerun_threshold or reruns >= config.max_reruns:
            break

        reruns += 1

        # Re-run agents focused on previously flagged lines
        flagged_by_file: dict = {}
        for f in all_findings:
            flagged_by_file.setdefault(f.filename, []).append(f.line_number)

        rerun_tasks = []
        for pf in pr_files:
            if pf.filename not in flagged_by_file:
                continue
            try:
                file_content = repo.get_contents(pf.filename, ref=head_sha).decoded_content.decode("utf-8")
                lines = file_content.split("\n")
                focused_lines = []
                for ln in flagged_by_file[pf.filename]:
                    start = max(0, ln - 3)
                    end = min(len(lines), ln + 3)
                    focused_lines.extend(lines[start:end])
                focused_context = "\n".join(focused_lines)
                rerun_tasks.append(
                    _analyze_file(client, pf.filename, pf.patch or "", focused_context, config, [])
                )
            except Exception:
                continue

        if rerun_tasks:
            rerun_results = await asyncio.gather(*rerun_tasks, return_exceptions=True)
            rerun_findings: List[Finding] = []
            for result in rerun_results:
                if not isinstance(result, Exception):
                    rerun_findings.extend(result)

            # Merge: keep highest confidence per (filename, line_number, agent)
            existing = {(f.filename, f.line_number, f.agent): f for f in all_findings}
            for rf in rerun_findings:
                key = (rf.filename, rf.line_number, rf.agent)
                if key not in existing or rf.confidence > existing[key].confidence:
                    existing[key] = rf
            all_findings = list(existing.values())

    return all_findings, skipped_files
