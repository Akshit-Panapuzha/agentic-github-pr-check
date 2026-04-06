import pytest
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
