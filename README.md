# Agentic GitHub PR Reviewer

An autonomous code review GitHub Action powered by OpenAI. On every pull request it analyses changed files, posts inline comments for issues it finds, and fails the run if anything is flagged — giving you a clear red/green signal alongside the review.

---

## Supported Languages

| Language | File types checked | Dependency CVE scan |
|----------|--------------------|---------------------|
| **Python** | `.py`, `requirements.txt`, `pyproject.toml` | PyPI via OSV |
| **C# / .NET** | `.cs`, `.csproj` | NuGet via OSV |

The action auto-detects language from file extensions. Both languages can be active at the same time (the default).

---

## Setup

### 1. Add your OpenAI API key as a secret

In your repo go to **Settings → Secrets and variables → Actions → New repository secret**.

| Secret name | Value |
|-------------|-------|
| `OPENAI_API_KEY` | Your OpenAI API key |

### 2. Create the workflow file

Create `.github/workflows/ai-review.yml` in your repo:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Run AI Code Reviewer
        uses: Akshit-Panapuzha/agentic-github-pr-check@v2
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          pr-number: ${{ github.event.pull_request.number }}
          repo: ${{ github.repository }}
          base-sha: ${{ github.event.pull_request.base.sha }}
          head-sha: ${{ github.event.pull_request.head.sha }}
```

That's it. Open a PR and the reviewer will run automatically.

---

## How it works

1. Fetches every changed file in the PR
2. Runs a **quality agent** (naming, complexity, dead code, syntax errors, async misuse) and a **security agent** (vulnerable dependencies via OSV, injection risks, secrets) in parallel per file
3. A **critique agent** scores each finding for confidence and filters out low-quality ones
4. Posts a single batched PR review with inline comments and a summary
5. **Exits with code 1** if any issues are found (fails the Actions run), code 0 if the PR is clean

---

## Configuration (optional)

Add a `.reviewer.yaml` to the root of your repo to customise behaviour:

```yaml
reviewer:
  reviewer_mode: default        # "default" = gpt-4o-mini (cheap), "production" = gpt-4o
  confidence_threshold: 0.65    # minimum confidence to post a finding
  max_comments_per_pr: 10       # cap on inline comments per run
  severity_filter:              # which severities to report
    - critical
    - high
    - medium
  languages:                    # limit to specific languages
    - python
    - csharp
  ignore_paths:                 # glob patterns to skip
    - "migrations/*"
    - "*.generated.cs"
  security:
    check_dependencies: true    # CVE scan via OSV
  quality:
    max_complexity: 10          # cyclomatic complexity threshold (Python only)
```

All fields are optional — the defaults shown above are used if the file is absent.

---

## Model tiers

| Mode | Models used | Best for |
|------|-------------|----------|
| `default` | `gpt-4o-mini` for all agents | Cost-effective, everyday use |
| `production` | `gpt-4o` for quality + security, `gpt-4o-mini` for critique | Thoroughness on critical PRs |

Switch modes per-run by setting `REVIEWER_MODE=production` as a repo variable, or set `reviewer_mode: production` in `.reviewer.yaml`.
