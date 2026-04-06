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
    with patch("reviewer.agents.security.check_package_vulnerabilities", return_value=vuln), \
         patch("reviewer.agents.security.parse_requirements", return_value=[("requests", "2.0.0")]):
        findings = await run_security_agent(
            client, "requirements.txt", "requests==2.0.0", "requests==2.0.0", config
        )
    assert any(f.title == "Vulnerable dependency: requests==2.0.0" for f in findings)


async def test_run_security_agent_uses_gpt4o_in_production_mode():
    client = make_mock_client([])
    config = ReviewerConfig(reviewer_mode="production")
    await run_security_agent(client, "src/foo.py", "code", "", config)
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"
