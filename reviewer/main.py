import asyncio
import os
import sys

from github import Github

from reviewer.config import load_config
from reviewer.github_client import post_review
from reviewer.orchestrator import run_pipeline
from reviewer.synthesizer import build_summary_body, synthesize


async def main() -> int:
    pr_number = int(os.environ["PR_NUMBER"])
    repo_name = os.environ["REPO"]
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    config = load_config()
    print(f"[reviewer] PR #{pr_number} on {repo_name}")
    print(f"[reviewer] Languages: {config.languages}")
    print(f"[reviewer] Mode: {config.reviewer_mode}")

    findings, skipped_files = await run_pipeline(pr_number, repo_name, base_sha, head_sha, config)
    print(f"[reviewer] Total findings before synthesis: {len(findings)}")
    for f in findings:
        print(f"[reviewer]   [{f.agent}][{f.severity}] {f.filename}:{f.line_number} confidence={f.confidence:.2f} — {f.title}")
    if skipped_files:
        print(f"[reviewer] Skipped files: {skipped_files}")

    inline, low_conf, truncated = synthesize(findings, config)
    print(f"[reviewer] Inline: {len(inline)}, Low-confidence: {len(low_conf)}, Truncated: {truncated}")

    summary = build_summary_body(inline, low_conf, skipped_files, truncated)

    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    post_review(repo, pr, head_sha, inline, summary)
    print("[reviewer] Review posted successfully.")

    if findings:
        print(f"[reviewer] Exiting with code 1 — {len(findings)} issue(s) found.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
