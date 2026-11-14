"""Embedding helper using OpenAI text-embedding-3-small with unit-normalized fallback."""

import hashlib
import math
import struct

from openai import AsyncOpenAI

from mongodb_hackathon.config import Settings, get_settings


def _normalize(vec: list[float]) -> list[float]:
    """Return L2-normalized vector (required for MongoDB dotProduct similarity)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return [1.0 / math.sqrt(len(vec))] * len(vec)
    return [x / norm for x in vec]


def deterministic_fallback_embedding(text: str, dimensions: int = 1536) -> list[float]:
    """Generate a deterministic normalized vector when no OpenAI key is configured (tests/offline)."""
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        for i in range(0, len(digest), 4):
            if len(values) >= dimensions:
                break
            raw = struct.unpack(">i", digest[i : i + 4])[0]
            values.append(raw / 2_147_483_647.0)
        counter += 1
    return _normalize(values)


async def embed_text(text: str, settings: Settings | None = None) -> list[float]:
    """Embed text using OpenAI if configured, otherwise deterministic normalized fallback."""
    cfg = settings or get_settings()
    if not cfg.openai_api_key:
        return deterministic_fallback_embedding(text, cfg.embedding_dimensions)

    client = AsyncOpenAI(api_key=cfg.openai_api_key)
    response = await client.embeddings.create(
        model=cfg.embedding_model,
        input=text[:12000],
    )
    return _normalize(list(response.data[0].embedding))
