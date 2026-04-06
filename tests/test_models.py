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
