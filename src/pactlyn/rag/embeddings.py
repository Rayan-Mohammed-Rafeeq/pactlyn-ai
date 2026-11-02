from __future__ import annotations

import hashlib
import math


class DeterministicTestEmbedding:
    """Deterministic embedding for tests and development without Ollama.

    Production semantic indexing should use ``OllamaProvider.embed``. This
    implementation is intentionally namespaced as a test/development adapter.
    """

    model_name = "deterministic-test"
    dimension = 64

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:2], "big") % self.dimension
                vector[index] += 1.0 if digest[2] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors
