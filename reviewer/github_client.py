import fnmatch
import os
import re
from typing import Dict, List

from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository

from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def parse_added_lines(patch: str) -> Dict[int, str]:
    """Return {line_number: content} for added lines only."""
    added = {}
    current_line = 0
    for line in patch.split("\n"):
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                current_line = int(match.group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            added[current_line] = line[1:]
        elif not line.startswith("-"):
            current_line += 1
    return added


def should_skip_file(filename: str, config: ReviewerConfig) -> bool:
    for pattern in config.ignore_paths:
        if filename.startswith(pattern) or fnmatch.fnmatch(filename, pattern):
            return True
    allowed_names = {"requirements.txt", "pyproject.toml"}
    if os.path.basename(filename) in allowed_names:
        return False
    _, ext = os.path.splitext(filename)
    return ext not in {".py"}


def post_review(
    repo: Repository,
    pr: PullRequest,
    head_sha: str,
    inline_findings: List[Finding],
    summary_body: str,
) -> None:
    """Post a single batched GitHub PR Review."""
    commit = repo.get_commit(head_sha)
    comments = [
        {
            "path": f.filename,
            "line": f.line_number,
            "body": f"**[{f.agent.upper()} | {f.severity.upper()}] {f.title}**\n\n{f.explanation}\n\n> {f.suggestion}",
        }
        for f in inline_findings
    ]
    pr.create_review(
        commit=commit,
        body=summary_body,
        event="COMMENT",
        comments=comments,
    )
