from typing import List

import numpy as np
from openai import AsyncOpenAI


def cosine_similarity(a: List[float], b: List[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def chunk_file_content(content: str, chunk_size: int = 50, overlap: int = 10) -> List[str]:
    lines = content.split("\n")
    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + chunk_size, len(lines))
        chunk = "\n".join(lines[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end == len(lines):
            break
        start += chunk_size - overlap
    return chunks


async def rank_chunks_by_relevance(
    client: AsyncOpenAI,
    query_text: str,
    chunks: List[str],
    token_budget: int = 5000,
) -> List[str]:
    if not chunks:
        return []

    all_texts = [query_text] + chunks
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=all_texts,
    )
    embeddings = [item.embedding for item in response.data]
    query_embedding = embeddings[0]
    chunk_embeddings = embeddings[1:]

    scored = sorted(
        zip(chunk_embeddings, chunks),
        key=lambda pair: cosine_similarity(query_embedding, pair[0]),
        reverse=True,
    )

    result = []
    total_tokens = 0
    for _, chunk in scored:
        chunk_tokens = len(chunk) // 4
        if total_tokens + chunk_tokens > token_budget:
            break
        result.append(chunk)
        total_tokens += chunk_tokens

    return result
