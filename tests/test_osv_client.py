import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


async def test_check_package_vulnerabilities_returns_vulns():
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
