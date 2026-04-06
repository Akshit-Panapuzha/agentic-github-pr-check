# Code Reviewer Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous GitHub PR code reviewer packaged as a public Docker-based GitHub Action that uses a 4-agent OpenAI pipeline to post inline review comments.

**Architecture:** Pure Python async pipeline — orchestrator fetches the diff, fans out to quality and security agents in parallel, scores findings through a critique agent, then the synthesizer posts a single batched GitHub PR Review. No framework; agents are plain async functions.

**Tech Stack:** Python 3.11, `openai` SDK (gpt-4o-mini / gpt-4o), `PyGithub`, `radon`, `httpx`, `PyYAML`, `pytest`, `pytest-asyncio`, Docker, GitHub Actions.

---

## File Map

| File | Responsibility |
|---|---|
| `reviewer/models.py` | `Finding` dataclass — shared type across all agents |
| `reviewer/config.py` | Load + validate `.reviewer.yaml`; env var precedence |
| `reviewer/embeddings.py` | OpenAI embeddings, cosine similarity, chunk ranking |
| `reviewer/github_client.py` | Fetch PR diff; post single batched PR Review |
| `reviewer/osv_client.py` | Query OSV API for dependency CVEs |
| `reviewer/prompts/quality.txt` | Quality agent system prompt |
| `reviewer/prompts/security.txt` | Security agent system prompt |
| `reviewer/prompts/critique.txt` | Critique agent system prompt |
| `reviewer/agents/quality.py` | Quality agent — style, complexity, dead code |
| `reviewer/agents/security.py` | Security agent — secrets, injection, CVEs |
| `reviewer/agents/critique.py` | Critique agent — confidence scoring |
| `reviewer/orchestrator.py` | Pipeline coordinator — context building, parallel execution, re-run loop |
| `reviewer/synthesizer.py` | Dedup, rank, cap, format, post GitHub review |
| `reviewer/main.py` | Entry point — reads env vars, kicks off pipeline |
| `action.yml` | GitHub Action definition |
| `Dockerfile` | Packages the reviewer for GitHub Actions |
| `.reviewer.yaml` | Default config for this repo itself |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `reviewer/__init__.py`
- Create: `reviewer/agents/__init__.py`
- Create: `reviewer/prompts/.gitkeep`
- Create: `tests/__init__.py`
- Create: `pytest.ini`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p reviewer/agents reviewer/prompts tests
touch reviewer/__init__.py reviewer/agents/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
PyGithub==2.3.0
openai==1.30.1
radon==6.0.1
PyYAML==6.0.1
httpx==0.27.0
numpy==1.26.4
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.2.0
pytest-asyncio==0.23.7
pytest-mock==3.14.0
```

- [ ] **Step 4: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements-dev.txt
```

Expected: All packages install without errors.

- [ ] **Step 6: Verify pytest runs**

```bash
pytest --collect-only
```

Expected: `no tests ran` with 0 errors.

- [ ] **Step 7: Commit**

```bash
git init
git add requirements.txt requirements-dev.txt pytest.ini reviewer/ tests/
git commit -m "chore: project scaffolding"
```

---

## Task 2: Models

**Files:**
- Create: `reviewer/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py
import pytest
from reviewer.models import Finding


def test_finding_id_is_generated_from_filename_line_agent():
    f = Finding(
        filename="src/auth.py",
        line_number=42,
        agent="quality",
        severity="high",
        title="Complex function",
        explanation="Too complex.",
        suggestion="Refactor.",
    )
    assert f.id != ""
    assert len(f.id) == 12


def test_finding_id_is_deterministic():
    f1 = Finding(filename="a.py", line_number=1, agent="quality",
                 severity="low", title="t", explanation="e", suggestion="s")
    f2 = Finding(filename="a.py", line_number=1, agent="quality",
                 severity="low", title="t", explanation="e", suggestion="s")
    assert f1.id == f2.id


def test_finding_id_differs_for_different_inputs():
    f1 = Finding(filename="a.py", line_number=1, agent="quality",
                 severity="low", title="t", explanation="e", suggestion="s")
    f2 = Finding(filename="a.py", line_number=2, agent="quality",
                 severity="low", title="t", explanation="e", suggestion="s")
    assert f1.id != f2.id


def test_finding_default_confidence_is_zero():
    f = Finding(filename="a.py", line_number=1, agent="security",
                severity="critical", title="t", explanation="e", suggestion="s")
    assert f.confidence == 0.0


def test_finding_explicit_id_is_preserved():
    f = Finding(filename="a.py", line_number=1, agent="quality",
                severity="low", title="t", explanation="e", suggestion="s",
                id="custom123")
    assert f.id == "custom123"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.models'`

- [ ] **Step 3: Implement `reviewer/models.py`**

```python
import hashlib
from dataclasses import dataclass, field


@dataclass
class Finding:
    filename: str
    line_number: int
    agent: str        # "quality" | "security"
    severity: str     # "critical" | "high" | "medium" | "low"
    title: str
    explanation: str
    suggestion: str
    confidence: float = 0.0
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            raw = f"{self.filename}{self.line_number}{self.agent}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/models.py tests/test_models.py
git commit -m "feat: Finding dataclass with deterministic id generation"
```

---

## Task 3: Config

**Files:**
- Create: `reviewer/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import os
import pytest
import yaml
from reviewer.config import load_config, ReviewerConfig


def test_load_config_returns_defaults_when_no_file(tmp_path):
    config = load_config(str(tmp_path / "nonexistent.yaml"))
    assert config.reviewer_mode == "default"
    assert config.confidence_threshold == 0.65
    assert config.rerun_threshold == 0.50
    assert config.max_reruns == 1
    assert config.max_comments_per_pr == 10
    assert config.severity_filter == ["critical", "high", "medium"]
    assert config.context_window_lines == 20
    assert config.token_budget_per_file == 5000
    assert config.security.check_dependencies is True
    assert config.quality.max_complexity == 10


def test_load_config_reads_yaml_values(tmp_path):
    yaml_content = {
        "reviewer": {
            "max_comments_per_pr": 5,
            "confidence_threshold": 0.8,
            "quality": {"max_complexity": 15},
        }
    }
    config_file = tmp_path / ".reviewer.yaml"
    config_file.write_text(yaml.dump(yaml_content))

    config = load_config(str(config_file))
    assert config.max_comments_per_pr == 5
    assert config.confidence_threshold == 0.8
    assert config.quality.max_complexity == 15
    assert config.max_reruns == 1  # default preserved


def test_env_var_overrides_yaml_reviewer_mode(tmp_path, monkeypatch):
    yaml_content = {"reviewer": {"reviewer_mode": "default"}}
    config_file = tmp_path / ".reviewer.yaml"
    config_file.write_text(yaml.dump(yaml_content))

    monkeypatch.setenv("REVIEWER_MODE", "production")
    config = load_config(str(config_file))
    assert config.reviewer_mode == "production"


def test_invalid_yaml_falls_back_to_defaults(tmp_path):
    config_file = tmp_path / ".reviewer.yaml"
    config_file.write_text(":::invalid yaml:::")

    config = load_config(str(config_file))
    assert config.reviewer_mode == "default"


def test_ignore_paths_defaults_to_empty(tmp_path):
    config = load_config(str(tmp_path / "nonexistent.yaml"))
    assert config.ignore_paths == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.config'`

- [ ] **Step 3: Implement `reviewer/config.py`**

```python
import os
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class SecurityConfig:
    check_dependencies: bool = True
    secret_patterns: List[str] = field(default_factory=list)


@dataclass
class QualityConfig:
    max_complexity: int = 10


@dataclass
class ReviewerConfig:
    reviewer_mode: str = "default"
    confidence_threshold: float = 0.65
    rerun_threshold: float = 0.50
    max_reruns: int = 1
    max_comments_per_pr: int = 10
    severity_filter: List[str] = field(default_factory=lambda: ["critical", "high", "medium"])
    context_window_lines: int = 20
    token_budget_per_file: int = 5000
    ignore_paths: List[str] = field(default_factory=list)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)


def load_config(path: str = ".reviewer.yaml") -> ReviewerConfig:
    data = {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pass
    except Exception:
        # Invalid YAML — fall back to defaults
        data = {}

    raw = data.get("reviewer", {})

    security_raw = raw.get("security", {})
    quality_raw = raw.get("quality", {})

    config = ReviewerConfig(
        reviewer_mode=raw.get("reviewer_mode", "default"),
        confidence_threshold=raw.get("confidence_threshold", 0.65),
        rerun_threshold=raw.get("rerun_threshold", 0.50),
        max_reruns=raw.get("max_reruns", 1),
        max_comments_per_pr=raw.get("max_comments_per_pr", 10),
        severity_filter=raw.get("severity_filter", ["critical", "high", "medium"]),
        context_window_lines=raw.get("context_window_lines", 20),
        token_budget_per_file=raw.get("token_budget_per_file", 5000),
        ignore_paths=raw.get("ignore_paths", []),
        security=SecurityConfig(
            check_dependencies=security_raw.get("check_dependencies", True),
            secret_patterns=security_raw.get("secret_patterns", []),
        ),
        quality=QualityConfig(
            max_complexity=quality_raw.get("max_complexity", 10),
        ),
    )

    # Env var takes precedence over .reviewer.yaml
    env_mode = os.environ.get("REVIEWER_MODE")
    if env_mode:
        config.reviewer_mode = env_mode

    return config
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/config.py tests/test_config.py
git commit -m "feat: config loader with env var precedence over .reviewer.yaml"
```

---

## Task 4: Embeddings

**Files:**
- Create: `reviewer/embeddings.py`
- Create: `tests/test_embeddings.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_embeddings.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from reviewer.embeddings import cosine_similarity, chunk_file_content, rank_chunks_by_relevance


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_chunk_file_content_splits_into_overlapping_chunks():
    lines = [f"line {i}" for i in range(100)]
    content = "\n".join(lines)
    chunks = chunk_file_content(content, chunk_size=20, overlap=5)
    assert len(chunks) > 1
    # Each chunk should contain roughly chunk_size lines
    first_chunk_lines = chunks[0].split("\n")
    assert len(first_chunk_lines) == 20


def test_chunk_file_content_short_file_returns_single_chunk():
    content = "line 1\nline 2\nline 3"
    chunks = chunk_file_content(content, chunk_size=20, overlap=5)
    assert len(chunks) == 1
    assert chunks[0] == content


async def test_rank_chunks_by_relevance_returns_within_token_budget():
    mock_client = AsyncMock()
    # Simulate embeddings: query + 3 chunks
    mock_client.embeddings.create.return_value = MagicMock(
        data=[
            MagicMock(embedding=[1.0, 0.0]),  # query
            MagicMock(embedding=[0.9, 0.1]),  # chunk 0 — most similar
            MagicMock(embedding=[0.0, 1.0]),  # chunk 1 — least similar
            MagicMock(embedding=[0.8, 0.2]),  # chunk 2 — second most similar
        ]
    )
    chunks = ["a " * 100, "b " * 100, "c " * 100]
    result = await rank_chunks_by_relevance(mock_client, "query text", chunks, token_budget=60)
    # With budget of 60 tokens (~240 chars), should fit 1 chunk (100 words * 1 char avg ≈ 100 tokens)
    # Actually 100 words * 2 chars/word = 200 chars / 4 = 50 tokens per chunk, so 1 chunk fits in 60
    assert len(result) >= 1
    # Most similar chunk (chunk 0 = "a " * 100) should appear first
    assert result[0] == chunks[0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_embeddings.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.embeddings'`

- [ ] **Step 3: Implement `reviewer/embeddings.py`**

```python
from typing import List
import numpy as np
from openai import AsyncOpenAI


def cosine_similarity(a: List[float], b: List[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def chunk_file_content(content: str, chunk_size: int = 50, overlap: int = 10) -> List[str]:
    lines = content.split("\n")
    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + chunk_size, len(lines))
        chunk = "\n".join(lines[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end == len(lines):
            break
        start += chunk_size - overlap
    return chunks


async def rank_chunks_by_relevance(
    client: AsyncOpenAI,
    query_text: str,
    chunks: List[str],
    token_budget: int = 5000,
) -> List[str]:
    if not chunks:
        return []

    all_texts = [query_text] + chunks
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=all_texts,
    )
    embeddings = [item.embedding for item in response.data]
    query_embedding = embeddings[0]
    chunk_embeddings = embeddings[1:]

    scored = sorted(
        zip(chunk_embeddings, chunks),
        key=lambda pair: cosine_similarity(query_embedding, pair[0]),
        reverse=True,
    )

    result = []
    total_tokens = 0
    for _, chunk in scored:
        # Estimate: 1 token ≈ 4 characters
        chunk_tokens = len(chunk) // 4
        if total_tokens + chunk_tokens > token_budget:
            break
        result.append(chunk)
        total_tokens += chunk_tokens

    return result
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_embeddings.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/embeddings.py tests/test_embeddings.py
git commit -m "feat: embeddings-based chunk ranking with cosine similarity"
```

---

## Task 5: GitHub Client

**Files:**
- Create: `reviewer/github_client.py`
- Create: `tests/test_github_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_github_client.py
import pytest
from unittest.mock import MagicMock, patch
from reviewer.github_client import parse_added_lines, should_skip_file
from reviewer.config import ReviewerConfig


def test_parse_added_lines_extracts_added_lines_with_line_numbers():
    patch = "@@ -10,3 +10,5 @@\n context\n+added line one\n+added line two\n context"
    result = parse_added_lines(patch)
    assert result == {11: "added line one", 12: "added line two"}


def test_parse_added_lines_ignores_removed_lines():
    patch = "@@ -1,2 +1,1 @@\n-removed\n+added"
    result = parse_added_lines(patch)
    assert result == {1: "added"}


def test_parse_added_lines_handles_multiple_hunks():
    patch = "@@ -1,1 +1,2 @@\n+first\n context\n@@ -10,1 +11,2 @@\n+second"
    result = parse_added_lines(patch)
    assert 1 in result
    assert result[1] == "first"


def test_should_skip_file_returns_true_for_ignored_path():
    config = ReviewerConfig(ignore_paths=["tests/", "migrations/"])
    assert should_skip_file("tests/test_foo.py", config) is True
    assert should_skip_file("migrations/0001_initial.py", config) is True


def test_should_skip_file_returns_false_for_normal_python_file():
    config = ReviewerConfig(ignore_paths=["tests/"])
    assert should_skip_file("src/auth.py", config) is False


def test_should_skip_file_returns_true_for_non_python_non_requirements():
    config = ReviewerConfig()
    assert should_skip_file("README.md", config) is True
    assert should_skip_file("static/app.js", config) is True


def test_should_skip_file_allows_requirements_files():
    config = ReviewerConfig()
    assert should_skip_file("requirements.txt", config) is False
    assert should_skip_file("pyproject.toml", config) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_github_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.github_client'`

- [ ] **Step 3: Implement `reviewer/github_client.py`**

```python
import fnmatch
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
    allowed_extensions = {".py"}
    allowed_names = {"requirements.txt", "pyproject.toml"}
    import os
    if os.path.basename(filename) in allowed_names:
        return False
    _, ext = os.path.splitext(filename)
    return ext not in allowed_extensions


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_github_client.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/github_client.py tests/test_github_client.py
git commit -m "feat: github client with diff parsing and PR review posting"
```

---

## Task 6: OSV Client

**Files:**
- Create: `reviewer/osv_client.py`
- Create: `tests/test_osv_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_osv_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from reviewer.osv_client import parse_requirements, parse_pyproject_deps, check_package_vulnerabilities


def test_parse_requirements_extracts_pinned_packages():
    content = "requests==2.31.0\nflask==3.0.0\n# comment\n\nblack"
    result = parse_requirements(content)
    assert ("requests", "2.31.0") in result
    assert ("flask", "3.0.0") in result


def test_parse_requirements_ignores_unpinned_and_comments():
    content = "# comment\nblack\nrequests>=2.0"
    result = parse_requirements(content)
    assert result == []


def test_parse_pyproject_deps_extracts_pinned_packages():
    content = '[project]\ndependencies = [\n    "requests==2.31.0",\n    "flask>=2.0",\n]\n'
    result = parse_pyproject_deps(content)
    assert ("requests", "2.31.0") in result
    assert all(name != "flask" for name, _ in result)


async def test_check_package_vulnerabilities_returns_vulns(respx_mock=None):
    import httpx
    with patch("reviewer.osv_client.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "vulns": [{"id": "GHSA-1234", "summary": "Test vuln"}]
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = await check_package_vulnerabilities("requests", "2.0.0")
        assert len(result) == 1
        assert result[0]["id"] == "GHSA-1234"


async def test_check_package_vulnerabilities_returns_empty_on_error():
    with patch("reviewer.osv_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.side_effect = Exception("network error")
        mock_client_cls.return_value = mock_client

        result = await check_package_vulnerabilities("requests", "2.0.0")
        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_osv_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.osv_client'`

- [ ] **Step 3: Implement `reviewer/osv_client.py`**

```python
import re
from typing import List, Tuple

import httpx

OSV_API_URL = "https://api.osv.dev/v1/query"


def parse_requirements(content: str) -> List[Tuple[str, str]]:
    packages = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
            packages.append((name.strip(), version.strip()))
    return packages


def parse_pyproject_deps(content: str) -> List[Tuple[str, str]]:
    packages = []
    pattern = re.compile(r'"([a-zA-Z0-9_-]+)==([^"]+)"')
    for match in pattern.finditer(content):
        packages.append((match.group(1), match.group(2)))
    return packages


async def check_package_vulnerabilities(package: str, version: str) -> List[dict]:
    payload = {
        "package": {"name": package, "ecosystem": "PyPI"},
        "version": version,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(OSV_API_URL, json=payload)
            response.raise_for_status()
            return response.json().get("vulns", [])
        except Exception:
            return []
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_osv_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/osv_client.py tests/test_osv_client.py
git commit -m "feat: OSV API client for dependency CVE lookups"
```

---

## Task 7: Prompts

**Files:**
- Create: `reviewer/prompts/quality.txt`
- Create: `reviewer/prompts/security.txt`
- Create: `reviewer/prompts/critique.txt`

- [ ] **Step 1: Write `reviewer/prompts/quality.txt`**

```
You are a senior Python engineer reviewing code changes in a pull request.
You will receive a code snippet with context and a cyclomatic complexity summary.

Analyze the code for:
- Style issues (PEP 8 violations, inconsistent formatting)
- Poor naming (unclear variable, function, or class names)
- High cyclomatic complexity (refer to the provided radon scores)
- Dead code (unreachable code, unused variables, unused imports)

Return ONLY a JSON object in this exact format:
{"findings": [...]}

Each finding in the array must have these exact keys:
{
  "filename": "path/to/file.py",
  "line_number": <integer — the line number of the issue>,
  "agent": "quality",
  "severity": "critical" | "high" | "medium" | "low",
  "title": "<short title, max 60 chars>",
  "explanation": "<one sentence explaining the issue>",
  "suggestion": "<one sentence suggesting a fix>"
}

If there are no issues, return: {"findings": []}

Rules:
- Only report issues on added/changed lines (lines starting with + in the diff context).
- Do not comment on unchanged surrounding context lines.
- Do not hallucinate issues. If you are uncertain, omit the finding.
- severity=critical: will cause crashes or data loss
- severity=high: significant maintainability or correctness concern
- severity=medium: noticeable issue worth fixing
- severity=low: minor style preference
```

- [ ] **Step 2: Write `reviewer/prompts/security.txt`**

```
You are a senior application security engineer reviewing code changes in a pull request.
You will receive a code snippet with context.

Analyze the code for:
- Hardcoded secrets (API keys, passwords, tokens, private keys, connection strings)
- SQL injection vulnerabilities
- Shell injection vulnerabilities (subprocess, os.system, eval)
- Path traversal vulnerabilities
- Other injection vulnerabilities (LDAP, XPath, template injection)

Return ONLY a JSON object in this exact format:
{"findings": [...]}

Each finding in the array must have these exact keys:
{
  "filename": "path/to/file.py",
  "line_number": <integer — the line number of the vulnerability>,
  "agent": "security",
  "severity": "critical" | "high" | "medium" | "low",
  "title": "<short title, max 60 chars>",
  "explanation": "<one sentence explaining the vulnerability>",
  "suggestion": "<one sentence suggesting a fix>"
}

If there are no issues, return: {"findings": []}

Severity rubric:
- critical: hardcoded API keys/passwords, SQL injection in any endpoint
- high: shell injection, path traversal, unparameterized queries
- medium: potential secret exposure, unvalidated input reaching sensitive operations
- low: weak patterns that could become vulnerabilities under certain conditions

Rules:
- Only report issues on added/changed lines.
- Do not report issues on deleted lines or unchanged context.
- Do not hallucinate vulnerabilities. Real findings only.
```

- [ ] **Step 3: Write `reviewer/prompts/critique.txt`**

```
You are a skeptical senior engineer reviewing the output of an automated code review tool.
You will receive a list of findings produced by quality and security analysis agents.

For each finding, decide:
- Is this a real issue or a false positive?
- Is the severity rating appropriate given what you can see?
- How confident are you that a developer should act on this?

Return ONLY a JSON object in this exact format:
{"scores": [...]}

Each item in the array must have these exact keys:
{
  "finding_id": "<the exact id value from the input finding>",
  "confidence": <float between 0.0 and 1.0>,
  "justification": "<one sentence explaining your confidence score>"
}

Scoring guide:
- 0.9–1.0: Clear, unambiguous issue — no reasonable developer would dispute it
- 0.7–0.9: Likely real issue, minor uncertainty about context
- 0.5–0.7: Plausible issue but depends on broader context not visible here
- 0.3–0.5: Probably a false positive or a matter of style preference
- 0.0–0.3: Almost certainly a false positive or irrelevant noise

You MUST return a score for every finding in the input. Do not skip any.
When in doubt, score lower rather than higher — false positives erode trust.
```

- [ ] **Step 4: Verify prompt files exist**

```bash
ls reviewer/prompts/
```

Expected: `critique.txt  quality.txt  security.txt`

- [ ] **Step 5: Commit**

```bash
git add reviewer/prompts/
git commit -m "feat: agent system prompts for quality, security, and critique"
```

---

## Task 8: Quality Agent

**Files:**
- Create: `reviewer/agents/quality.py`
- Create: `tests/test_agents_quality.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agents_quality.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from reviewer.agents.quality import run_quality_agent
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def make_mock_client(findings_json: list) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content=json.dumps({"findings": findings_json})
        ))]
    )
    return mock_client


async def test_run_quality_agent_returns_findings():
    raw_finding = {
        "filename": "src/auth.py",
        "line_number": 10,
        "agent": "quality",
        "severity": "medium",
        "title": "Poorly named variable",
        "explanation": "Variable 'x' is not descriptive.",
        "suggestion": "Rename to 'user_token'.",
    }
    client = make_mock_client([raw_finding])
    config = ReviewerConfig()

    findings = await run_quality_agent(client, "src/auth.py", "code context", "complexity: N/A", config)

    assert len(findings) == 1
    assert isinstance(findings[0], Finding)
    assert findings[0].filename == "src/auth.py"
    assert findings[0].line_number == 10
    assert findings[0].agent == "quality"
    assert findings[0].id != ""


async def test_run_quality_agent_returns_empty_on_no_findings():
    client = make_mock_client([])
    config = ReviewerConfig()
    findings = await run_quality_agent(client, "src/foo.py", "code", "complexity: N/A", config)
    assert findings == []


async def test_run_quality_agent_uses_gpt4o_in_production_mode():
    client = make_mock_client([])
    config = ReviewerConfig(reviewer_mode="production")
    await run_quality_agent(client, "src/foo.py", "code", "complexity: N/A", config)
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"


async def test_run_quality_agent_uses_gpt4o_mini_in_default_mode():
    client = make_mock_client([])
    config = ReviewerConfig(reviewer_mode="default")
    await run_quality_agent(client, "src/foo.py", "code", "complexity: N/A", config)
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"


async def test_run_quality_agent_returns_empty_on_malformed_json():
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not json at all"))]
    )
    config = ReviewerConfig()
    findings = await run_quality_agent(mock_client, "src/foo.py", "code", "N/A", config)
    assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agents_quality.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.agents.quality'`

- [ ] **Step 3: Implement `reviewer/agents/quality.py`**

```python
import json
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from reviewer.config import ReviewerConfig
from reviewer.models import Finding

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "quality.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


async def run_quality_agent(
    client: AsyncOpenAI,
    filename: str,
    context: str,
    complexity_summary: str,
    config: ReviewerConfig,
) -> List[Finding]:
    model = "gpt-4o" if config.reviewer_mode == "production" else "gpt-4o-mini"
    system_prompt = _load_prompt()
    user_message = f"File: {filename}\n\n{complexity_summary}\n\nCode:\n{context}"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        findings_data = raw.get("findings", [])
    except Exception:
        return []

    return [
        Finding(
            filename=d.get("filename", filename),
            line_number=int(d.get("line_number", 0)),
            agent="quality",
            severity=d.get("severity", "low"),
            title=d.get("title", ""),
            explanation=d.get("explanation", ""),
            suggestion=d.get("suggestion", ""),
        )
        for d in findings_data
        if isinstance(d, dict)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agents_quality.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/agents/quality.py tests/test_agents_quality.py
git commit -m "feat: quality agent with gpt-4o-mini/gpt-4o model split"
```

---

## Task 9: Security Agent

**Files:**
- Create: `reviewer/agents/security.py`
- Create: `tests/test_agents_security.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agents_security.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from reviewer.agents.security import run_security_agent
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def make_mock_client(findings_json: list) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content=json.dumps({"findings": findings_json})
        ))]
    )
    return mock_client


async def test_run_security_agent_returns_findings():
    raw_finding = {
        "filename": "src/db.py",
        "line_number": 5,
        "agent": "security",
        "severity": "critical",
        "title": "Hardcoded API key",
        "explanation": "API key is hardcoded in source.",
        "suggestion": "Use environment variable instead.",
    }
    client = make_mock_client([raw_finding])
    config = ReviewerConfig()

    findings = await run_security_agent(client, "src/db.py", "code context", "", config)
    assert len(findings) == 1
    assert findings[0].agent == "security"
    assert findings[0].severity == "critical"


async def test_run_security_agent_returns_empty_on_no_findings():
    client = make_mock_client([])
    config = ReviewerConfig()
    findings = await run_security_agent(client, "src/foo.py", "code", "", config)
    assert findings == []


async def test_run_security_agent_checks_deps_for_requirements_file():
    client = make_mock_client([])
    config = ReviewerConfig()

    vuln = [{"id": "GHSA-1234", "summary": "Test vulnerability"}]
    with patch("reviewer.agents.security.check_package_vulnerabilities", return_value=vuln) as mock_osv, \
         patch("reviewer.agents.security.parse_requirements", return_value=[("requests", "2.0.0")]):
        findings = await run_security_agent(
            client, "requirements.txt", "requests==2.0.0", "requests==2.0.0", config
        )
    mock_osv.assert_called_once_with("requests", "2.0.0")
    assert any(f.title == "Vulnerable dependency: requests==2.0.0" for f in findings)


async def test_run_security_agent_uses_gpt4o_in_production_mode():
    client = make_mock_client([])
    config = ReviewerConfig(reviewer_mode="production")
    await run_security_agent(client, "src/foo.py", "code", "", config)
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agents_security.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.agents.security'`

- [ ] **Step 3: Implement `reviewer/agents/security.py`**

```python
import asyncio
import json
import os
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from reviewer.config import ReviewerConfig
from reviewer.models import Finding
from reviewer.osv_client import check_package_vulnerabilities, parse_requirements, parse_pyproject_deps

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "security.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


async def _check_dependencies(filename: str, content: str) -> List[Finding]:
    findings = []
    if filename == "requirements.txt":
        packages = parse_requirements(content)
    elif filename == "pyproject.toml":
        packages = parse_pyproject_deps(content)
    else:
        return []

    tasks = [check_package_vulnerabilities(name, version) for name, version in packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for (name, version), vulns in zip(packages, results):
        if isinstance(vulns, Exception) or not vulns:
            continue
        for vuln in vulns:
            findings.append(
                Finding(
                    filename=filename,
                    line_number=1,
                    agent="security",
                    severity="high",
                    title=f"Vulnerable dependency: {name}=={version}",
                    explanation=vuln.get("summary", "Known vulnerability found."),
                    suggestion=f"Upgrade {name} to a patched version. See {vuln.get('id', 'OSV')}.",
                )
            )
    return findings


async def run_security_agent(
    client: AsyncOpenAI,
    filename: str,
    context: str,
    patch: str,
    config: ReviewerConfig,
) -> List[Finding]:
    model = "gpt-4o" if config.reviewer_mode == "production" else "gpt-4o-mini"
    system_prompt = _load_prompt()
    user_message = f"File: {filename}\n\nCode:\n{context}"

    llm_findings = []
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        findings_data = raw.get("findings", [])
        llm_findings = [
            Finding(
                filename=d.get("filename", filename),
                line_number=int(d.get("line_number", 0)),
                agent="security",
                severity=d.get("severity", "low"),
                title=d.get("title", ""),
                explanation=d.get("explanation", ""),
                suggestion=d.get("suggestion", ""),
            )
            for d in findings_data
            if isinstance(d, dict)
        ]
    except Exception:
        pass

    dep_findings = []
    if config.security.check_dependencies and filename in ("requirements.txt", "pyproject.toml"):
        dep_findings = await _check_dependencies(filename, patch)

    return llm_findings + dep_findings
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agents_security.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/agents/security.py tests/test_agents_security.py
git commit -m "feat: security agent with injection detection and OSV dependency checks"
```

---

## Task 10: Critique Agent

**Files:**
- Create: `reviewer/agents/critique.py`
- Create: `tests/test_agents_critique.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agents_critique.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from reviewer.agents.critique import run_critique_agent
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def make_finding(filename="a.py", line=1, agent="quality", severity="medium"):
    return Finding(
        filename=filename, line_number=line, agent=agent, severity=severity,
        title="test", explanation="test", suggestion="test"
    )


def make_mock_client(scores: list) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content=json.dumps({"scores": scores})
        ))]
    )
    return mock_client


async def test_critique_agent_applies_confidence_scores():
    f = make_finding()
    scores = [{"finding_id": f.id, "confidence": 0.9, "justification": "Clearly an issue."}]
    client = make_mock_client(scores)
    config = ReviewerConfig()

    result = await run_critique_agent(client, [f], config)
    assert len(result) == 1
    assert result[0].confidence == 0.9


async def test_critique_agent_always_uses_gpt4o_mini():
    f = make_finding()
    scores = [{"finding_id": f.id, "confidence": 0.8, "justification": "ok"}]
    client = make_mock_client(scores)

    for mode in ["default", "production"]:
        config = ReviewerConfig(reviewer_mode=mode)
        await run_critique_agent(client, [f], config)
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"


async def test_critique_agent_batches_per_file_in_production_mode():
    f1 = make_finding(filename="a.py", line=1)
    f2 = make_finding(filename="a.py", line=2)
    f3 = make_finding(filename="b.py", line=1)

    call_count = 0
    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        msgs = kwargs["messages"]
        user_content = msgs[1]["content"]
        # Find which findings are in this batch and return scores for them
        import json as j
        data = j.loads(user_content)
        scores = [{"finding_id": d["id"], "confidence": 0.8, "justification": "ok"}
                  for d in data["findings"]]
        return MagicMock(choices=[MagicMock(message=MagicMock(
            content=j.dumps({"scores": scores})
        ))])

    client = AsyncMock()
    client.chat.completions.create = mock_create
    config = ReviewerConfig(reviewer_mode="production")

    result = await run_critique_agent(client, [f1, f2, f3], config)
    assert call_count == 2  # one call per file (a.py and b.py)
    assert len(result) == 3


async def test_critique_agent_returns_original_findings_on_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = Exception("API error")
    config = ReviewerConfig()
    findings = [make_finding()]
    result = await run_critique_agent(client, findings, config)
    assert len(result) == 1
    assert result[0].confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agents_critique.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.agents.critique'`

- [ ] **Step 3: Implement `reviewer/agents/critique.py`**

```python
import json
from collections import defaultdict
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from reviewer.config import ReviewerConfig
from reviewer.models import Finding

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "critique.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _apply_scores(findings: List[Finding], scores: list) -> List[Finding]:
    score_map = {s["finding_id"]: s["confidence"] for s in scores if "finding_id" in s}
    for f in findings:
        if f.id in score_map:
            f.confidence = score_map[f.id]
    return findings


async def _score_batch(client: AsyncOpenAI, findings: List[Finding]) -> list:
    system_prompt = _load_prompt()
    findings_payload = [
        {
            "id": f.id,
            "filename": f.filename,
            "line_number": f.line_number,
            "agent": f.agent,
            "severity": f.severity,
            "title": f.title,
            "explanation": f.explanation,
        }
        for f in findings
    ]
    user_message = json.dumps({"findings": findings_payload})
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(response.choices[0].message.content)
    return raw.get("scores", [])


async def run_critique_agent(
    client: AsyncOpenAI,
    findings: List[Finding],
    config: ReviewerConfig,
) -> List[Finding]:
    if not findings:
        return findings

    try:
        if config.reviewer_mode == "production":
            # One call per file batch
            by_file = defaultdict(list)
            for f in findings:
                by_file[f.filename].append(f)

            import asyncio
            tasks = [_score_batch(client, file_findings) for file_findings in by_file.values()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_scores = []
            for result in results:
                if not isinstance(result, Exception):
                    all_scores.extend(result)
        else:
            # One call, all findings batched
            all_scores = await _score_batch(client, findings)

        return _apply_scores(findings, all_scores)
    except Exception:
        return findings
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agents_critique.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/agents/critique.py tests/test_agents_critique.py
git commit -m "feat: critique agent with per-batch and per-file scoring modes"
```

---

## Task 11: Orchestrator

**Files:**
- Create: `reviewer/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from reviewer.orchestrator import compute_complexity, build_file_context, run_pipeline
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def test_compute_complexity_returns_string():
    source = "def foo(x):\n    if x:\n        return 1\n    return 0\n"
    result = compute_complexity(source)
    assert "foo" in result or "complexity" in result.lower()


def test_compute_complexity_handles_invalid_source():
    result = compute_complexity("not valid python ::::")
    assert "could not compute" in result


async def test_build_file_context_returns_full_content_within_budget():
    client = AsyncMock()
    config = ReviewerConfig(token_budget_per_file=50000)
    content = "line\n" * 10
    patch_str = "@@ -1,1 +1,2 @@\n+new line"

    result = await build_file_context(client, "a.py", patch_str, content, config)
    assert result == content


async def test_build_file_context_uses_embeddings_when_over_budget():
    client = AsyncMock()
    # Simulate embeddings call
    client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[1.0, 0.0])] * 10
    )
    # Large content that exceeds token budget
    content = "x = 1\n" * 5000  # ~20k chars = ~5000 tokens
    config = ReviewerConfig(token_budget_per_file=100)
    patch_str = "@@ -1,1 +1,2 @@\n+new line"

    result = await build_file_context(client, "a.py", patch_str, content, config)
    assert result is not None
    assert len(result) < len(content)


async def test_build_file_context_returns_none_for_empty_patch():
    client = AsyncMock()
    config = ReviewerConfig()
    result = await build_file_context(client, "a.py", "", "content", config)
    assert result is None


async def test_run_pipeline_skips_non_python_files():
    config = ReviewerConfig()
    mock_file = MagicMock()
    mock_file.filename = "README.md"
    mock_file.patch = "@@ -1 +1 @@\n+change"

    with patch("reviewer.orchestrator.Github") as mock_gh, \
         patch("reviewer.orchestrator.AsyncOpenAI"):
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.get_files.return_value = [mock_file]
        mock_repo.get_pull.return_value = mock_pr
        mock_gh.return_value.get_repo.return_value = mock_repo

        findings, skipped = await run_pipeline(1, "org/repo", "abc", "def", config)
        assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.orchestrator'`

- [ ] **Step 3: Implement `reviewer/orchestrator.py`**

```python
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
from reviewer.github_client import parse_added_lines, should_skip_file
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

    # Estimate tokens: 1 token ≈ 4 chars
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
    file_names = []

    for f in pr.get_files():
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
        file_names.append(f.filename)

    results = await asyncio.gather(*file_tasks, return_exceptions=True)

    all_findings: List[Finding] = []
    for result in results:
        if not isinstance(result, Exception):
            all_findings.extend(result)

    # Filter by severity
    all_findings = [f for f in all_findings if f.severity in config.severity_filter]

    # Critique loop
    reruns = 0
    while True:
        all_findings = await run_critique_agent(client, all_findings, config)

        if not all_findings:
            break

        avg_confidence = sum(f.confidence for f in all_findings) / len(all_findings)
        if avg_confidence >= config.rerun_threshold or reruns >= config.max_reruns:
            break

        reruns += 1
        # Re-run agents with tighter prompt (focus on previously flagged lines)
        flagged = {(f.filename, f.line_number) for f in all_findings}
        rerun_tasks = []
        for f in pr.get_files():
            if not any(f.filename == fname for fname, _ in flagged):
                continue
            try:
                file_content = repo.get_contents(f.filename, ref=head_sha).decoded_content.decode("utf-8")
            except Exception:
                continue

            focused_context = "\n".join(
                f"Line {ln}: {repo.get_contents(f.filename, ref=head_sha).decoded_content.decode('utf-8').split(chr(10))[ln - 1]}"
                for fname, ln in flagged
                if fname == f.filename
            )
            rerun_tasks.append(
                _analyze_file(client, f.filename, f.patch or "", focused_context, config, [])
            )

        if rerun_tasks:
            rerun_results = await asyncio.gather(*rerun_tasks, return_exceptions=True)
            rerun_findings: List[Finding] = []
            for result in rerun_results:
                if not isinstance(result, Exception):
                    rerun_findings.extend(result)

            # Merge: deduplicate by (filename, line_number, agent), keep higher confidence
            existing = {(f.filename, f.line_number, f.agent): f for f in all_findings}
            for rf in rerun_findings:
                key = (rf.filename, rf.line_number, rf.agent)
                if key not in existing or rf.confidence > existing[key].confidence:
                    existing[key] = rf
            all_findings = list(existing.values())

    return all_findings, skipped_files
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator with parallel analysis, critique loop, and re-run logic"
```

---

## Task 12: Synthesizer

**Files:**
- Create: `reviewer/synthesizer.py`
- Create: `tests/test_synthesizer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_synthesizer.py
import pytest
from unittest.mock import MagicMock, patch
from reviewer.synthesizer import deduplicate, sort_findings, build_summary_body, synthesize
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def make_finding(filename="a.py", line=1, agent="quality", severity="medium", confidence=0.8):
    return Finding(
        filename=filename, line_number=line, agent=agent, severity=severity,
        title="Test", explanation="Test explanation.", suggestion="Fix it.",
        confidence=confidence
    )


def test_deduplicate_keeps_higher_confidence_for_same_line():
    f1 = make_finding(line=1, agent="quality", confidence=0.7)
    f2 = make_finding(line=1, agent="security", confidence=0.9)
    result = deduplicate([f1, f2])
    # Both are kept — different agents
    assert len(result) == 2


def test_deduplicate_removes_exact_duplicate_same_agent():
    f1 = make_finding(line=1, agent="quality", confidence=0.7)
    f2 = make_finding(line=1, agent="quality", confidence=0.9)
    result = deduplicate([f1, f2])
    assert len(result) == 1
    assert result[0].confidence == 0.9


def test_sort_findings_orders_by_severity_then_confidence():
    critical = make_finding(severity="critical", confidence=0.8)
    high_low_conf = make_finding(severity="high", confidence=0.6)
    high_high_conf = make_finding(severity="high", confidence=0.9)
    medium = make_finding(severity="medium", confidence=0.7)

    result = sort_findings([medium, high_low_conf, critical, high_high_conf])
    assert result[0].severity == "critical"
    assert result[1].confidence == 0.9  # high+0.9 before high+0.6
    assert result[-1].severity == "medium"


def test_build_summary_body_includes_severity_groups():
    findings = [
        make_finding(severity="critical", confidence=0.9),
        make_finding(severity="high", confidence=0.8),
    ]
    low_conf = [make_finding(severity="medium", confidence=0.4)]
    body = build_summary_body(findings, low_conf, skipped_files=[], truncated_count=0)
    assert "critical" in body.lower()
    assert "high" in body.lower()
    assert "<details>" in body
    assert "low-confidence" in body.lower()


def test_build_summary_body_includes_truncation_notice():
    findings = [make_finding()]
    body = build_summary_body(findings, [], skipped_files=[], truncated_count=3)
    assert "3 additional" in body


def test_build_summary_body_includes_skipped_files_notice():
    findings = []
    body = build_summary_body(findings, [], skipped_files=["large_file.py"], truncated_count=0)
    assert "large_file.py" in body


def test_synthesize_caps_inline_comments():
    findings = [make_finding(line=i, confidence=0.9) for i in range(15)]
    config = ReviewerConfig(max_comments_per_pr=10, confidence_threshold=0.65)
    inline, low_conf, truncated = synthesize(findings, config)
    assert len(inline) == 10
    assert truncated == 5


def test_synthesize_moves_low_confidence_to_separate_list():
    high = make_finding(confidence=0.9)
    low = make_finding(line=2, confidence=0.4)
    config = ReviewerConfig(confidence_threshold=0.65, max_comments_per_pr=10)
    inline, low_conf, truncated = synthesize([high, low], config)
    assert high in inline
    assert low in low_conf
    assert truncated == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_synthesizer.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.synthesizer'`

- [ ] **Step 3: Implement `reviewer/synthesizer.py`**

```python
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
    """Split findings into (inline, low_confidence, truncated_count)."""
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
                sections.append(f"- **{f.title}** (`{f.filename}:{f.line_number}`) — {f.explanation}")

    if truncated_count > 0:
        sections.append(
            f"\n> **{truncated_count} additional finding(s) suppressed.** "
            f"Increase `max_comments_per_pr` in `.reviewer.yaml` to see them."
        )

    if skipped_files:
        sections.append(f"\n> **Skipped files** (exceeded token budget or unreadable): {', '.join(skipped_files)}")

    if low_conf:
        items = "\n".join(
            f"- **{f.title}** (`{f.filename}:{f.line_number}`, confidence: {f.confidence:.2f}) — {f.explanation}"
            for f in low_conf
        )
        sections.append(
            f"\n<details>\n<summary>Low-confidence findings ({len(low_conf)})</summary>\n\n{items}\n\n</details>"
        )

    return "\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_synthesizer.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer/synthesizer.py tests/test_synthesizer.py
git commit -m "feat: synthesizer with dedup, severity sorting, cap, and collapsible low-confidence section"
```

---

## Task 13: Entry Point

**Files:**
- Create: `reviewer/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_main.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os


async def test_main_reads_env_vars_and_runs_pipeline(monkeypatch):
    monkeypatch.setenv("PR_NUMBER", "42")
    monkeypatch.setenv("REPO", "org/repo")
    monkeypatch.setenv("BASE_SHA", "abc123")
    monkeypatch.setenv("HEAD_SHA", "def456")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("reviewer.main.run_pipeline", new_callable=AsyncMock) as mock_pipeline, \
         patch("reviewer.main.synthesize") as mock_synth, \
         patch("reviewer.main.build_summary_body") as mock_body, \
         patch("reviewer.main.post_review") as mock_post, \
         patch("reviewer.main.Github") as mock_gh:

        mock_pipeline.return_value = ([], [])
        mock_synth.return_value = ([], [], 0)
        mock_body.return_value = "summary"
        mock_gh.return_value.get_repo.return_value.get_pull.return_value = MagicMock()

        from reviewer.main import main
        await main()

        mock_pipeline.assert_called_once_with(42, "org/repo", "abc123", "def456", pytest.ANY)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer.main'`

- [ ] **Step 3: Implement `reviewer/main.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_main.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add reviewer/main.py tests/test_main.py
git commit -m "feat: main entry point wiring pipeline, synthesizer, and GitHub posting"
```

---

## Task 14: GitHub Action Packaging

**Files:**
- Create: `action.yml`
- Create: `Dockerfile`
- Create: `.reviewer.yaml`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY reviewer/ ./reviewer/
COPY .reviewer.yaml .

ENTRYPOINT ["python", "-m", "reviewer.main"]
```

- [ ] **Step 2: Write `action.yml`**

```yaml
name: 'AI Code Reviewer'
description: 'Autonomous PR code review using OpenAI. Configurable via .reviewer.yaml.'
branding:
  icon: 'eye'
  color: 'blue'
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

- [ ] **Step 3: Write `.reviewer.yaml` (defaults for this repo)**

```yaml
reviewer:
  reviewer_mode: default
  confidence_threshold: 0.65
  rerun_threshold: 0.50
  max_reruns: 1
  max_comments_per_pr: 10
  severity_filter: [critical, high, medium]
  context_window_lines: 20
  token_budget_per_file: 5000
  ignore_paths:
    - "tests/"
    - "docs/"
  security:
    check_dependencies: true
    secret_patterns: []
  quality:
    max_complexity: 10
```

- [ ] **Step 4: Write the example target repo workflow**

Create `docs/example-workflow.yml` so adopters can copy it:

```yaml
# .github/workflows/ai-review.yml
# Copy this file into any repo that wants AI code review.
# Add OPENAI_API_KEY as a repository secret (Settings → Secrets → Actions).

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
          # reviewer-mode: production  # uncomment for gpt-4o analysis
```

- [ ] **Step 5: Verify Dockerfile builds**

```bash
docker build -t reviewer-test .
```

Expected: Build succeeds, image created.

- [ ] **Step 6: Run full test suite one final time**

```bash
pytest -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit and tag**

```bash
git add action.yml Dockerfile .reviewer.yaml docs/example-workflow.yml
git commit -m "feat: Docker-based GitHub Action packaging with action.yml"
git tag v0.1.0
```

---

## Final Checklist

- [ ] All tests pass: `pytest -v`
- [ ] Docker image builds: `docker build -t reviewer-test .`
- [ ] No hardcoded API keys or secrets anywhere in the codebase
- [ ] `.reviewer.yaml` present at repo root
- [ ] `docs/example-workflow.yml` present for adopters
- [ ] Repo is public and tagged `v0.1.0`
