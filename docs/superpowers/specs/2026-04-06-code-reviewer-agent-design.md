# Autonomous Code Reviewer Agent — Design Document

**Status:** Approved  
**Author:** Akshit Panapuzha  
**Last updated:** April 2026

---

## Overview

An autonomous GitHub PR code reviewer packaged as a public, reusable GitHub Action. Any repo can adopt it by referencing `akshitpanapuzha/agentic-github-pr-check@v1` in a workflow file and adding an `OPENAI_API_KEY` secret. Behavior is configurable per-repo via a `.reviewer.yaml` file.

The system uses a multi-agent pipeline to analyze pull requests for code quality issues and security vulnerabilities, then posts a single structured GitHub PR Review with inline comments. A self-critique loop scores each finding before posting, filtering low-confidence results into a collapsible section to keep review noise low.

---

## Goals

- Automatically review every PR for code quality and security issues without manual triggering
- Post findings as a single batched GitHub PR Review with inline comments at relevant line numbers
- Keep false-positive rates low via an internal critique and scoring pass
- Be configurable per-repo via a `.reviewer.yaml` file
- Run entirely within GitHub Actions — no external server required
- Be distributable as a public GitHub Action usable across any repo

### Non-goals

- Replacing human code review (the agent assists, it does not approve/merge)
- Supporting languages other than Python in v1
- Fixing code automatically (read-only; suggestions only)

---

## Architecture

Pure Python async pipeline. No multi-agent framework — agents are plain async functions orchestrated by a single orchestrator module using `asyncio`. One API provider (OpenAI) handles both LLM calls and embeddings.

```
GitHub PR event
      │
      ▼
  Orchestrator
  - Reads env vars (PR_NUMBER, REPO, BASE_SHA, HEAD_SHA)
  - Fetches diff via PyGithub
  - Filters generated/vendored/non-Python files
  - Embeds changed lines per file (text-embedding-3-small)
  - Builds windowed context per file (≤5k tokens, ranked by cosine similarity)
  - Fans out to Quality + Security agents in parallel (asyncio)
      │
      ├── Quality Agent
      └── Security Agent
            │
            ▼
      Critique Agent
      - default mode → one call, all findings batched
      - production mode → one call per file's findings
      - Findings below confidence_threshold → collapsible section
      - If avg confidence < rerun_threshold → re-run (up to max_reruns)
            │
            ▼
      Synthesizer
      - Deduplicates on (filename, line_number)
      - Sorts by severity then confidence
      - Caps at max_comments_per_pr (default 10), adds notice if truncated
      - Posts single GitHub PR Review: inline comments + summary + collapsible section
```

---

## Agent Responsibilities

### Orchestrator (`orchestrator.py`)
- Receives PR context from env vars
- Fetches full diff using PyGithub
- Filters out: ignored paths, generated files, non-Python files, binary files
- For each remaining file: embeds added lines, ranks surrounding chunks by cosine similarity, packs context up to 5k token ceiling
- If file still exceeds budget after trimming: skips file, notes it in summary
- Calls quality and security agents in parallel via `asyncio`
- Manages re-run loop up to `max_reruns`

### Quality Agent (`agents/quality.py`)
- Receives windowed context (≤5k tokens) + radon complexity score pre-injected as metadata
- Analyzes for style issues, poor naming, high cyclomatic complexity, dead code
- Returns JSON list of findings
- Model: `gpt-4o-mini` (default) / `gpt-4o` (production)

### Security Agent (`agents/security.py`)
- Same windowed context approach
- Scans for hardcoded secrets, injection vulnerabilities (SQL, shell, path traversal)
- For `requirements.txt` / `pyproject.toml` changes: queries OSV API for CVEs in added/updated dependencies
- Returns findings with severity (`critical` / `high` / `medium` / `low`)
- Model: `gpt-4o-mini` (default) / `gpt-4o` (production)

### Critique Agent (`agents/critique.py`)
- Always uses `gpt-4o-mini` — scoring does not require the heavy model
- Receives findings output from quality + security agents
- Acts as a skeptical senior engineer: outputs confidence score (0.0–1.0) and one-sentence justification per finding
- `REVIEWER_MODE=default`: one call, all findings batched together
- `REVIEWER_MODE=production`: one call per file batch
- Findings below `confidence_threshold` (default 0.65) → moved to collapsible section, not dropped
- If avg confidence < `rerun_threshold` (default 0.50) → orchestrator triggers re-run with tighter prompt, merges results, up to `max_reruns` (default 1)

### Synthesizer (`synthesizer.py`)
- Deduplicates findings on `(filename, line_number)` — same line flagged by both agents merges into one comment
- Sorts by severity then confidence
- Caps inline comments at `max_comments_per_pr` (default 10)
- Posts a single GitHub PR Review (Pull Request Reviews API — batched, atomic):
  - Inline comments at each `filename` + `line_number`
  - Top-level summary comment grouped by severity
  - `<details>` collapsible block for low-confidence findings
  - Truncation notice if cap was hit

---

## Data Flow

### Input

Env vars injected by GitHub Actions:

```
OPENAI_API_KEY
GITHUB_TOKEN       # auto-provided by Actions
PR_NUMBER
REPO
BASE_SHA
HEAD_SHA
REVIEWER_MODE      # optional: "default" (default) or "production"
```

### Per-file context building

1. Extract `added_lines` from diff (deleted lines ignored)
2. Embed added lines using `text-embedding-3-small`
3. Split full file into overlapping chunks
4. Embed each chunk, rank by cosine similarity to added lines
5. Pack highest-ranked chunks until 5k token ceiling is hit
6. Inject radon complexity score as metadata header (quality agent only)

### Finding schema

```python
@dataclass
class Finding:
    id: str           # md5(filename + line_number + agent) — used by critique agent to match scores back
    filename: str
    line_number: int
    agent: str        # "quality" | "security"
    severity: str     # "critical" | "high" | "medium" | "low"
    title: str
    explanation: str
    suggestion: str
    confidence: float # populated by critique agent
```

### Output

- Inline PR review comments at each `filename` + `line_number`
- Top-level summary comment listing all findings grouped by severity
- Collapsible `<details>` block for low-confidence findings
- Truncation notice if `max_comments_per_pr` was hit
- If no findings: posts "No issues found" summary, zero inline comments

---

## Tech Stack

| Component | Library / Service |
|---|---|
| GitHub integration | `PyGithub` |
| LLM calls (all agents) | `openai` Python SDK — `gpt-4o-mini` (default) / `gpt-4o` (production) |
| Embeddings | `openai` Python SDK — `text-embedding-3-small` |
| Parallel agent execution | `asyncio` |
| Complexity scoring | `radon` |
| Dependency CVE lookup | OSV API (free, no key needed) |
| Trigger + runtime | GitHub Actions (Docker action) |
| Configuration | `.reviewer.yaml` per repo |

Single API key required: `OPENAI_API_KEY`.

**Configuration precedence:** env vars take priority over `.reviewer.yaml`. If `REVIEWER_MODE` is set as an env var (via the action input), it overrides `reviewer_mode` in `.reviewer.yaml`. This allows per-run overrides without modifying the config file.

---

## Configuration

`.reviewer.yaml` at the repo root. All fields optional — defaults apply if file is missing or a field is omitted.

```yaml
reviewer:
  # Model behavior
  reviewer_mode: default           # "default" (gpt-4o-mini) or "production" (gpt-4o for analysis)

  # Critique loop
  confidence_threshold: 0.65       # findings below this → collapsible section
  rerun_threshold: 0.50            # re-run agents if avg confidence below this
  max_reruns: 1                    # cap on re-run cycles

  # Output
  max_comments_per_pr: 10          # hard cap; truncation notice posted if hit
  severity_filter: [critical, high, medium]  # skip "low" findings

  # Context window
  context_window_lines: 20         # ±N lines around changed lines
  token_budget_per_file: 5000      # ceiling before embeddings-based trimming kicks in

  # File filtering
  ignore_paths:
    - "tests/"
    - "migrations/"
    - "*.generated.py"

  # Security
  security:
    check_dependencies: true
    secret_patterns: []            # extra regex patterns for secret detection

  # Quality
  quality:
    max_complexity: 10             # radon cyclomatic complexity threshold
```

---

## GitHub Action Packaging

Packaged as a Docker-based GitHub Action for consistent, portable execution across any runner.

### `action.yml`

```yaml
name: 'AI Code Reviewer'
description: 'Autonomous PR code review using OpenAI. Configurable via .reviewer.yaml.'
inputs:
  openai-api-key:
    description: 'OpenAI API key'
    required: true
  reviewer-mode:
    description: '"default" (gpt-4o-mini, cheapest) or "production" (gpt-4o for analysis agents)'
    required: false
    default: 'default'
runs:
  using: 'docker'
  image: 'Dockerfile'
  env:
    OPENAI_API_KEY: ${{ inputs.openai-api-key }}
    REVIEWER_MODE: ${{ inputs.reviewer-mode }}
    GITHUB_TOKEN: ${{ github.token }}
    PR_NUMBER: ${{ github.event.pull_request.number }}
    REPO: ${{ github.repository }}
    BASE_SHA: ${{ github.event.pull_request.base.sha }}
    HEAD_SHA: ${{ github.event.pull_request.head.sha }}
```

### Target repo usage

After publishing and tagging `v1`, any repo adopts the reviewer with:

```yaml
# .github/workflows/ai-review.yml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: akshitpanapuzha/agentic-github-pr-check@v1
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

Optionally add `.reviewer.yaml` at the repo root to customize behavior.

### Secrets management

**Personal repos (current):** Add `OPENAI_API_KEY` as a repository secret on each repo that adopts the action.
```
Repo Settings → Secrets and variables → Actions → New secret → OPENAI_API_KEY
```

**GitHub org (future upgrade path):** Create a single organization secret named `OPENAI_API_KEY` and grant access to all repositories. No workflow file changes needed — `${{ secrets.OPENAI_API_KEY }}` resolves identically. One place to rotate or revoke the key across all repos.

---

## Project Structure

```
agentic-github-pr-check/
├── action.yml                   # GitHub Action definition
├── Dockerfile                   # packages the reviewer
├── reviewer/
│   ├── main.py                  # entry point, reads env vars, kicks off pipeline
│   ├── orchestrator.py          # fetches diff, builds context, routes to agents, manages re-runs
│   ├── agents/
│   │   ├── quality.py           # quality sub-agent
│   │   ├── security.py          # security sub-agent
│   │   └── critique.py          # critique + scoring agent
│   ├── synthesizer.py           # dedup, rank, format, post to GitHub
│   ├── github_client.py         # thin wrapper around PyGithub
│   ├── osv_client.py            # OSV API dependency lookup
│   ├── embeddings.py            # OpenAI embedding + cosine similarity ranking
│   ├── models.py                # Finding dataclass and related types
│   ├── config.py                # loads and validates .reviewer.yaml
│   └── prompts/
│       ├── quality.txt          # quality agent system prompt
│       ├── security.txt         # security agent system prompt
│       └── critique.txt         # critique agent system prompt
├── requirements.txt
└── .reviewer.yaml               # defaults for this repo itself
```

---

## Prompt Design

- **Scoped context:** Quality and security agents receive one file at a time, not the entire diff
- **Structured output:** All agents instructed to return JSON only
- **Explicit severity rubric:** Security agent prompt includes severity definitions to reduce inconsistency (e.g., hardcoded API keys always `critical`)
- **Role framing:** Critique agent is framed as a "skeptical senior engineer" — produces more useful pushback on weak findings
- **Critique output schema:** `[{finding_id, confidence, justification}]`

---

## Error Handling

| Scenario | Behavior |
|---|---|
| OpenAI API timeout | Retry up to 3 times with exponential backoff; skip agent if all retries fail |
| OpenAI rate limit | Wait and retry; log warning |
| Malformed agent JSON output | Log and skip that agent's findings for this file |
| OSV API unavailable | Skip dependency check; note in summary comment |
| PR has no changed Python files | Post no comments; exit cleanly |
| `.reviewer.yaml` is invalid | Fall back to defaults; log warning comment on the PR |
| File exceeds 5k token budget after embedding trim | Skip file; note in summary comment |
| GitHub rate limit hit | Wait and retry; log warning |
| `max_reruns` reached, avg confidence still low | Accept findings as-is; borderline ones go to collapsible section |
| No findings after critique | Post "No issues found" summary; zero inline comments |

---

## Milestones

| Phase | Scope |
|---|---|
| v0.1 | Orchestrator + quality agent, hardcoded config, no critique loop, no Action packaging |
| v0.2 | Security agent, OSV dependency check, parallel execution, embeddings-based context |
| v0.3 | Critique agent + scoring loop, `.reviewer.yaml` config, re-run cap |
| v1.0 | Full pipeline, batched GitHub PR Review, collapsible low-confidence section, Docker Action packaging, `@v1` tag |
