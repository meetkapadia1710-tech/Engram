"""Provider-agnostic AI layer.

Two capabilities, each behind a tiny interface:

* ``Embedder.embed(texts) -> list[vector]``
* ``Generator.generate(prompt) -> str``          (summaries, titles)

Providers: OpenAI, Gemini, Ollama, Anthropic (generation), plus a fully-local
fallback for both so Engram runs with zero API keys. Selection is config-only —
callers never import a concrete provider.
"""

from __future__ import annotations

import hashlib
import math
import re

import httpx

from .config import settings

# --------------------------------------------------------------------------
# Embedders
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have i if in into is it its me my
    no not of on or our so that the their then there these they this to was we
    were what when where which who will with you your""".split()
)


def _stem(t: str) -> str:
    """Suffix-stripping stemmer (Porter-lite): folds plurals and -ing/-ed forms
    so 'caching', 'cached' and 'layers', 'layer' land on the same feature."""
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t


def _raw_tokens(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in _raw_tokens(text)]


class LocalEmbedder:
    """Deterministic feature-hashing embedder (unigrams + bigrams, signed
    hashing trick, L2-normalized). No model download, no network, fully
    reproducible — ideal for tests, air-gapped installs, and small deployments.
    """

    name = "local"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or settings.local_embedding_dim

    def _slot(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "big") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            toks = _tokens(text)
            feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for f in feats:
                idx, sign = self._slot(f)
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class OpenAIEmbedder:
    name = "openai"

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": settings.openai_embedding_model, "input": texts},
            timeout=60,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class GeminiEmbedder:
    name = "gemini"

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            "models/text-embedding-004:batchEmbedContents"
        )
        body = {
            "requests": [
                {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": t}]},
                }
                for t in texts
            ]
        }
        r = httpx.post(
            url, params={"key": settings.gemini_api_key}, json=body, timeout=60
        )
        r.raise_for_status()
        return [e["values"] for e in r.json()["embeddings"]]


class OllamaEmbedder:
    name = "ollama"

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.ollama_embedding_model, "input": texts},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["embeddings"]


# --------------------------------------------------------------------------
# Generators (summaries / titles)
# --------------------------------------------------------------------------


class LocalGenerator:
    """Extractive fallback: no LLM required. Picks the most keyword-dense
    sentences, which is good enough for titles/summaries of short memories."""

    name = "local"

    def generate(self, prompt: str, source_text: str = "") -> str:
        text = source_text or prompt
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if not sentences:
            return ""
        freq: dict[str, int] = {}
        for t in _tokens(text):
            freq[t] = freq.get(t, 0) + 1
        scored = sorted(
            sentences,
            key=lambda s: sum(freq.get(t, 0) for t in _tokens(s)) / (len(_tokens(s)) or 1),
            reverse=True,
        )
        return " ".join(scored[:2]).strip()


class OpenAIGenerator:
    name = "openai"

    def generate(self, prompt: str, source_text: str = "") -> str:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.generation_model or "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class AnthropicGenerator:
    name = "anthropic"

    def generate(self, prompt: str, source_text: str = "") -> str:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": settings.generation_model or "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()


class GeminiGenerator:
    name = "gemini"

    def generate(self, prompt: str, source_text: str = "") -> str:
        model = settings.generation_model or "gemini-2.0-flash"
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


class OllamaGenerator:
    name = "ollama"

    def generate(self, prompt: str, source_text: str = "") -> str:
        r = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.generation_model or "qwen2.5:3b",
                "prompt": prompt,
                "stream": False,
            },
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["response"].strip()


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------

_EMBEDDERS = {
    "local": LocalEmbedder,
    "openai": OpenAIEmbedder,
    "gemini": GeminiEmbedder,
    "ollama": OllamaEmbedder,
}
_GENERATORS = {
    "local": LocalGenerator,
    "openai": OpenAIGenerator,
    "anthropic": AnthropicGenerator,
    "gemini": GeminiGenerator,
    "ollama": OllamaGenerator,
}

_embedder_cache: dict[str, object] = {}


def get_embedder():
    name = settings.embedding_provider
    if name not in _EMBEDDERS:
        raise ValueError(f"unknown embedding provider: {name!r}")
    if name not in _embedder_cache:
        _embedder_cache[name] = _EMBEDDERS[name]()
    return _embedder_cache[name]


def get_generator():
    name = settings.generation_provider
    if name not in _GENERATORS:
        raise ValueError(f"unknown generation provider: {name!r}")
    return _GENERATORS[name]()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)
