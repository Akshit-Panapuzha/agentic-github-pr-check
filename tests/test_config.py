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
    assert config.max_reruns == 1


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
