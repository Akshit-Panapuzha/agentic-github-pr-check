import asyncio
import json
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from reviewer.config import ReviewerConfig
from reviewer.models import Finding
from reviewer.osv_client import check_package_vulnerabilities, parse_pyproject_deps, parse_requirements

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "security.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


async def _check_dependencies(filename: str, content: str) -> List[Finding]:
    findings = []
    if filename == "requirements.txt":
        packages = parse_requirements(content)
    elif filename == "pyproject.toml":
        packages = parse_pyproject_deps(content)
    else:
        return []

    tasks = [check_package_vulnerabilities(name, version) for name, version in packages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for (name, version), vulns in zip(packages, results):
        if isinstance(vulns, Exception) or not vulns:
            continue
        for vuln in vulns:
            findings.append(
                Finding(
                    filename=filename,
                    line_number=1,
                    agent="security",
                    severity="high",
                    title=f"Vulnerable dependency: {name}=={version}",
                    explanation=vuln.get("summary", "Known vulnerability found."),
                    suggestion=f"Upgrade {name} to a patched version. See {vuln.get('id', 'OSV')}.",
                )
            )
    return findings


async def run_security_agent(
    client: AsyncOpenAI,
    filename: str,
    context: str,
    patch: str,
    config: ReviewerConfig,
) -> List[Finding]:
    model = "gpt-4o" if config.reviewer_mode == "production" else "gpt-4o-mini"
    system_prompt = _load_prompt()
    user_message = f"File: {filename}\n\nCode:\n{context}"

    llm_findings = []
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(response.choices[0].message.content)
        findings_data = raw.get("findings", [])
        llm_findings = [
            Finding(
                filename=d.get("filename", filename),
                line_number=int(d.get("line_number", 0)),
                agent="security",
                severity=d.get("severity", "low"),
                title=d.get("title", ""),
                explanation=d.get("explanation", ""),
                suggestion=d.get("suggestion", ""),
            )
            for d in findings_data
            if isinstance(d, dict)
        ]
    except Exception:
        pass

    dep_findings = []
    if config.security.check_dependencies and filename in ("requirements.txt", "pyproject.toml"):
        dep_findings = await _check_dependencies(filename, patch)

    return llm_findings + dep_findings
