import asyncio
import os

from github import Github

from reviewer.config import load_config
from reviewer.github_client import post_review
from reviewer.orchestrator import run_pipeline
from reviewer.synthesizer import build_summary_body, synthesize


async def main() -> None:
    pr_number = int(os.environ["PR_NUMBER"])
    repo_name = os.environ["REPO"]
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    config = load_config()

    findings, skipped_files = await run_pipeline(pr_number, repo_name, base_sha, head_sha, config)
    inline, low_conf, truncated = synthesize(findings, config)
    summary = build_summary_body(inline, low_conf, skipped_files, truncated)

    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    post_review(repo, pr, head_sha, inline, summary)


if __name__ == "__main__":
    asyncio.run(main())
