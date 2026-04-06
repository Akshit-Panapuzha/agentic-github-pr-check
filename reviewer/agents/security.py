import asyncio
import json
from pathlib import Path
from typing import List

from openai import AsyncOpenAI, RateLimitError, APITimeoutError

from reviewer.config import ReviewerConfig
from reviewer.models import Finding
from reviewer.osv_client import check_package_vulnerabilities, parse_pyproject_deps, parse_requirements

_PROMPT_PATHS = {
    "python": Path(__file__).parent.parent / "prompts" / "security.txt",
    "csharp": Path(__file__).parent.parent / "prompts" / "security_csharp.txt",
}


def _load_prompt(language: str) -> str:
    path = _PROMPT_PATHS.get(language, _PROMPT_PATHS["python"])
    return path.read_text()


async def _check_dependencies(filename: str, content: str, language: str = "python") -> List[Finding]:
    findings = []
    ecosystem = "NuGet" if language == "csharp" else "PyPI"

    if filename == "requirements.txt":
        packages = parse_requirements(content)
    elif filename == "pyproject.toml":
        packages = parse_pyproject_deps(content)
    elif filename.endswith(".csproj"):
        from reviewer.osv_client import parse_csproj_deps
        packages = parse_csproj_deps(content)
    else:
        return []

    tasks = [check_package_vulnerabilities(name, version, ecosystem) for name, version in packages]
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
    language: str = "python",
) -> List[Finding]:
    model = "gpt-4o" if config.reviewer_mode == "production" else "gpt-4o-mini"
    system_prompt = _load_prompt(language)
    user_message = f"File: {filename}\n\nCode:\n{context}"

    findings_data = []
    for attempt in range(3):
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
            raw_content = response.choices[0].message.content
            print(f"[security] {filename}: raw response: {raw_content[:300]}")
            raw = json.loads(raw_content)
            findings_data = raw.get("findings", [])
            print(f"[security] {filename}: {len(findings_data)} findings")
            break
        except (RateLimitError, APITimeoutError) as e:
            wait = 2 ** attempt
            print(f"[security] {filename}: rate limit/timeout (attempt {attempt+1}), retrying in {wait}s — {e}")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"[security] {filename}: ERROR — {e}")
            break

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

    dep_files = {"requirements.txt", "pyproject.toml"} | {f for f in [filename] if f.endswith(".csproj")}
    dep_findings = []
    if config.security.check_dependencies and filename in dep_files:
        dep_findings = await _check_dependencies(filename, patch, language)

    return llm_findings + dep_findings
