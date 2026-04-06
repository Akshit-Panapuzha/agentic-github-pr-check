# Autonomous Code Reviewer — Design Document

**Status:** Draft  
**Author:** TBD  
**Last updated:** April 2026  

---

## Overview

This document describes the architecture, implementation plan, and design decisions for an autonomous GitHub PR code reviewer built on top of the Claude API. The system uses a multi-agent pipeline to analyze pull requests for code quality issues and security vulnerabilities, then posts structured inline comments directly on the PR via the GitHub API.

The key differentiator from simple LLM-based linters is a self-critique loop: a dedicated agent scores each finding before it gets posted, filtering out low-confidence results and keeping review noise low.

---

## Goals

- Automatically review every PR for code quality and security issues without manual triggering
- Post findings as inline GitHub PR comments at the relevant line numbers
- Keep false-positive rates low via an internal critique and scoring pass
- Be configurable per-repo via a `.reviewer.yaml` file
- Run entirely within GitHub Actions — no external server required

### Non-goals

- Replacing human code review (the agent assists, it does not approve/merge)
- Supporting languages other than Python in v1
- Fixing code automatically (read-only; suggestions only)

---

## Architecture

The system is structured as a pipeline of four agents that run sequentially with internal parallelism:

```
GitHub PR event
      │
      ▼
┌─────────────────────┐
│   Orchestrator      │  Fetches diff, splits by file, routes to sub-agents
└──────┬──────────────┘
       │ (parallel)
  ┌────┴────────────────────┐
  │                         │
  ▼                         ▼
┌──────────────┐   ┌──────────────────┐
│ Quality      │   │ Security         │
│ Agent        │   │ Agent            │
│              │   │                  │
│ Style        │   │ Secrets          │
│ Complexity   │   │ Injection        │
│ Dead code    │   │ Dependency CVEs  │
└──────┬───────┘   └──────┬───────────┘
       │                  │
       └────────┬─────────┘
                ▼
     ┌──────────────────────┐
     │  Critique Agent      │  Scores each finding; drops low-confidence ones
     └──────────┬───────────┘
                │ (re-runs if avg score < threshold)
                ▼
     ┌──────────────────────┐
     │  Synthesizer         │  Deduplicates, ranks, formats for GitHub
     └──────────┬───────────┘
                ▼
       GitHub PR comments
       (inline + summary)
```

### Agent responsibilities

**Orchestrator**
- Receives the webhook payload from GitHub Actions
- Fetches the full PR diff using `PyGithub`
- Splits the diff by file and filters out generated/vendored files
- Calls the quality and security agents in parallel using `asyncio`
- Passes combined results to the critique agent

**Quality agent**
- Analyzes changed files for style issues, poor naming, high cyclomatic complexity, and dead code
- Uses `radon` to compute complexity scores before calling Claude, so the LLM has concrete metrics to reason about
- System prompt is scoped to a single file at a time to keep context focused

**Security agent**
- Scans for hardcoded secrets (API keys, passwords, tokens)
- Detects common injection vulnerabilities (SQL, shell, path traversal)
- For any changed `requirements.txt` or `pyproject.toml`, queries the OSV API to check for known CVEs in added or updated dependencies
- Returns findings with severity (`critical`, `high`, `medium`, `low`) and a one-line explanation

**Critique agent**
- Receives the combined output of the quality and security agents
- Acts as a skeptical senior engineer: for each finding, it outputs a confidence score (0.0–1.0) and a brief justification
- Any finding below `confidence_threshold` (default `0.65`, configurable) is either dropped or downgraded to a `low-confidence` label
- If the average confidence across all findings is below `rerun_threshold` (default `0.5`), the orchestrator re-runs the quality and security agents with a tighter prompt and merges the second pass

**Synthesizer**
- Deduplicates findings that refer to the same line from different agents
- Sorts by severity then confidence
- Formats output as GitHub review comments (inline) and a top-level summary comment

---

## Data flow

### Input

A GitHub `pull_request` event triggers the Actions workflow. The orchestrator receives:

```json
{
  "pr_number": 42,
  "repo": "org/repo",
  "base_sha": "abc123",
  "head_sha": "def456"
}
```

### Diff processing

The orchestrator fetches the diff and parses it into file-level chunks:

```python
{
  "filename": "src/auth/login.py",
  "patch": "@@ -12,6 +12,9 @@ ...",
  "added_lines": {14: "token = request.args.get('token')", ...},
  "language": "python"
}
```

Only `added_lines` are reviewed — deleted lines are ignored.

### Finding schema

Each agent returns a list of findings in this structure:

```python
@dataclass
class Finding:
    filename: str
    line_number: int
    agent: str           # "quality" | "security"
    severity: str        # "critical" | "high" | "medium" | "low"
    title: str
    explanation: str
    suggestion: str
    confidence: float    # added by critique agent
```

### Output

The synthesizer posts:
- Inline PR review comments at the relevant `filename` + `line_number`
- A top-level summary comment listing all findings grouped by severity

---

## Tech stack

| Component | Library / Service |
|---|---|
| GitHub integration | `PyGithub` |
| LLM calls | `anthropic` Python SDK — `claude-sonnet-4-6` |
| Parallel agent execution | `asyncio` |
| Complexity scoring | `radon` |
| Dependency CVE lookup | OSV API (free, no key needed) |
| Trigger + runtime | GitHub Actions |
| Configuration | `.reviewer.yaml` per repo |

---

## Configuration

Each repo can include a `.reviewer.yaml` at the root to customize behavior:

```yaml
reviewer:
  confidence_threshold: 0.65      # drop findings below this score
  rerun_threshold: 0.50           # re-run agents if avg confidence is below this
  max_comments_per_pr: 20         # cap to avoid overwhelming reviewers
  severity_filter: [critical, high, medium]  # skip "low" findings
  ignore_paths:
    - "tests/"
    - "migrations/"
    - "*.generated.py"
  security:
    check_dependencies: true
    secret_patterns: []           # optional extra regex patterns
  quality:
    max_complexity: 10            # radon cyclomatic complexity threshold
```

If no `.reviewer.yaml` is present, all defaults apply.

---

## Self-critique loop

This is the most important part of the design. Most automated review tools fail in production because they're noisy — developers learn to ignore them.

The critique agent is a second Claude call that receives the raw findings and is asked to play the role of a skeptical senior engineer. Its prompt is roughly:

> You are reviewing the output of an automated code review tool. For each finding, decide: is this a real issue? Is the severity correct? Could this be a false positive? Output a confidence score from 0.0 to 1.0 and a one-sentence justification.

If a finding scores below `confidence_threshold`, it is dropped from the final output entirely. This means the system may post zero comments on a PR — which is correct behavior when the code is clean.

If the overall batch scores poorly (average below `rerun_threshold`), the orchestrator triggers a second analysis pass with a more constrained prompt focused only on the lines flagged in the first pass. Results from both passes are merged and de-duplicated before the final critique.

---

## GitHub Actions workflow

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r reviewer/requirements.txt

      - name: Run code reviewer
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          REPO: ${{ github.repository }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: python -m reviewer.main
```

---

## Project structure

```
reviewer/
├── main.py                  # entry point, reads env vars, kicks off pipeline
├── orchestrator.py          # fetches diff, routes to agents, manages re-runs
├── agents/
│   ├── quality.py           # quality sub-agent
│   ├── security.py          # security sub-agent
│   └── critique.py          # critique + scoring agent
├── synthesizer.py           # dedup, rank, format, post to GitHub
├── github_client.py         # thin wrapper around PyGithub
├── osv_client.py            # OSV API dependency lookup
├── models.py                # Finding dataclass and related types
├── config.py                # loads and validates .reviewer.yaml
├── prompts/
│   ├── quality.txt          # quality agent system prompt
│   ├── security.txt         # security agent system prompt
│   └── critique.txt         # critique agent system prompt
└── requirements.txt
```

---

## Prompt design notes

Each sub-agent has a system prompt stored in `prompts/`. Key principles:

- **Scoped context:** The quality and security agents receive one file at a time, not the entire diff. This keeps the context window small and outputs precise.
- **Structured output:** All agents are instructed to return JSON only. The critique agent outputs a list of `{finding_id, confidence, justification}` objects.
- **Explicit severity definitions:** The security agent's prompt includes a severity rubric to reduce inconsistency. Hardcoded API keys are always `critical`. SQL injection in a non-authenticated endpoint is `high`. Unused imports are `low`.
- **Role framing for critique:** Framing the critique agent as a "skeptical senior engineer" rather than a "validator" produces more useful pushback on weak findings.

---

## Error handling

| Scenario | Behavior |
|---|---|
| Claude API timeout | Retry up to 3 times with exponential backoff; skip agent if all retries fail |
| GitHub rate limit hit | Wait and retry; log warning |
| Malformed agent JSON output | Log and skip that agent's findings for this run |
| OSV API unavailable | Skip dependency check; note in summary comment |
| PR has no changed Python files | Post no comments; exit cleanly |
| `.reviewer.yaml` is invalid | Fall back to defaults; log a warning comment on the PR |

---

## Milestones

| Phase | Scope |
|---|---|
| v0.1 | Orchestrator + quality agent only, hardcoded config, no critique loop |
| v0.2 | Security agent added, OSV dependency check, parallel execution |
| v0.3 | Critique agent + scoring loop, `.reviewer.yaml` config support |
| v1.0 | Full pipeline, inline GitHub comments, summary comment, max comment cap |

---

## Open questions

- Should the critique agent run once per finding or once per batch? Per-batch is cheaper but per-finding may produce better justifications.
- What's the right default for `max_comments_per_pr`? Too low and real issues get dropped; too high and the PR becomes overwhelming.
- Should `low-confidence` findings be posted under a collapsible section rather than dropped entirely? Keeps them visible without adding noise.
- How do we handle minified or auto-generated files that slip through the ignore list?
