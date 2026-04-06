import pytest
from reviewer.synthesizer import deduplicate, sort_findings, build_summary_body, synthesize
from reviewer.config import ReviewerConfig
from reviewer.models import Finding


def make_finding(filename="a.py", line=1, agent="quality", severity="medium", confidence=0.8):
    return Finding(
        filename=filename, line_number=line, agent=agent, severity=severity,
        title="Test", explanation="Test explanation.", suggestion="Fix it.",
        confidence=confidence
    )


def test_deduplicate_keeps_both_when_different_agents():
    f1 = make_finding(line=1, agent="quality", confidence=0.7)
    f2 = make_finding(line=1, agent="security", confidence=0.9)
    result = deduplicate([f1, f2])
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
    assert result[1].confidence == 0.9
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
    body = build_summary_body([], [], skipped_files=["large_file.py"], truncated_count=0)
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
