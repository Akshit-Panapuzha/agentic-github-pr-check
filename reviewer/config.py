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
