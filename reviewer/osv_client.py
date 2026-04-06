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
