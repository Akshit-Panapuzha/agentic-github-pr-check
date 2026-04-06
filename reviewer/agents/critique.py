import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import List

from openai import AsyncOpenAI

from reviewer.config import ReviewerConfig
from reviewer.models import Finding

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "critique.txt"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def _apply_scores(findings: List[Finding], scores: list) -> List[Finding]:
    score_map = {s["finding_id"]: s["confidence"] for s in scores if "finding_id" in s}
    for f in findings:
        if f.id in score_map:
            f.confidence = score_map[f.id]
    return findings


async def _score_batch(client: AsyncOpenAI, findings: List[Finding]) -> list:
    system_prompt = _load_prompt()
    findings_payload = [
        {
            "id": f.id,
            "filename": f.filename,
            "line_number": f.line_number,
            "agent": f.agent,
            "severity": f.severity,
            "title": f.title,
            "explanation": f.explanation,
        }
        for f in findings
    ]
    user_message = json.dumps({"findings": findings_payload})
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(response.choices[0].message.content)
    return raw.get("scores", [])


async def run_critique_agent(
    client: AsyncOpenAI,
    findings: List[Finding],
    config: ReviewerConfig,
) -> List[Finding]:
    if not findings:
        return findings

    try:
        if config.reviewer_mode == "production":
            by_file = defaultdict(list)
            for f in findings:
                by_file[f.filename].append(f)

            tasks = [_score_batch(client, file_findings) for file_findings in by_file.values()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_scores = []
            for result in results:
                if not isinstance(result, Exception):
                    all_scores.extend(result)
        else:
            all_scores = await _score_batch(client, findings)

        return _apply_scores(findings, all_scores)
    except Exception:
        return findings
