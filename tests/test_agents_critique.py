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
        data = json.loads(kwargs["messages"][1]["content"])
        scores = [{"finding_id": d["id"], "confidence": 0.8, "justification": "ok"}
                  for d in data["findings"]]
        return MagicMock(choices=[MagicMock(message=MagicMock(
            content=json.dumps({"scores": scores})
        ))])

    client = AsyncMock()
    client.chat.completions.create = mock_create
    config = ReviewerConfig(reviewer_mode="production")

    result = await run_critique_agent(client, [f1, f2, f3], config)
    assert call_count == 2
    assert len(result) == 3


async def test_critique_agent_returns_original_findings_on_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = Exception("API error")
    config = ReviewerConfig()
    findings = [make_finding()]
    result = await run_critique_agent(client, findings, config)
    assert len(result) == 1
    assert result[0].confidence == 0.0
