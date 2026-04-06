import json
import pytest
from unittest.mock import AsyncMock, MagicMock
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
