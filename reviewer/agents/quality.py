import asyncio
import json
from pathlib import Path
from typing import List

from openai import AsyncOpenAI, RateLimitError, APITimeoutError

from reviewer.config import ReviewerConfig
from reviewer.models import Finding

_PROMPT_PATHS = {
    "python": Path(__file__).parent.parent / "prompts" / "quality.txt",
    "csharp": Path(__file__).parent.parent / "prompts" / "quality_csharp.txt",
}


def _load_prompt(language: str) -> str:
    path = _PROMPT_PATHS.get(language, _PROMPT_PATHS["python"])
    return path.read_text()


async def run_quality_agent(
    client: AsyncOpenAI,
    filename: str,
    context: str,
    complexity_summary: str,
    config: ReviewerConfig,
    language: str = "python",
) -> List[Finding]:
    model = "gpt-4o" if config.reviewer_mode == "production" else "gpt-4o-mini"
    system_prompt = _load_prompt(language)
    user_message = f"File: {filename}\n\n{complexity_summary}\n\nCode:\n{context}"

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
            print(f"[quality] {filename}: raw response: {raw_content[:300]}")
            raw = json.loads(raw_content)
            findings_data = raw.get("findings", [])
            print(f"[quality] {filename}: {len(findings_data)} findings")
            break
        except (RateLimitError, APITimeoutError) as e:
            wait = 2 ** attempt
            print(f"[quality] {filename}: rate limit/timeout (attempt {attempt+1}), retrying in {wait}s — {e}")
            await asyncio.sleep(wait)
            findings_data = []
        except Exception as e:
            print(f"[quality] {filename}: ERROR — {e}")
            return []

    return [
        Finding(
            filename=d.get("filename", filename),
            line_number=int(d.get("line_number", 0)),
            agent="quality",
            severity=d.get("severity", "low"),
            title=d.get("title", ""),
            explanation=d.get("explanation", ""),
            suggestion=d.get("suggestion", ""),
        )
        for d in findings_data
        if isinstance(d, dict)
    ]
