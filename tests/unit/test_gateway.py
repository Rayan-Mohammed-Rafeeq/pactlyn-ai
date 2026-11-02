from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pactlyn.llm.gateway import LLMGateway


class UnavailableProvider:
    name = "ollama"
    is_local = True

    async def available(self):
        return False

    async def complete(self, messages, *, json_schema=None):
        raise AssertionError("completion must not run when provider is unavailable")

    async def stream(self, messages):
        yield ""

    async def list_models(self):
        return []


class StructuredProvider:
    name = "ollama"
    is_local = True

    async def available(self):
        return True

    async def complete(self, messages, *, json_schema=None):
        assert "Current time" in messages[1]["content"]
        assert "Known contact" in messages[1]["content"]
        return json.dumps({
            "candidates": [
                {"title": "Send proposal", "description": "Send the proposal", "type": "personal_task", "needs_confirmation": True},
                {"title": "Wait for reply", "description": "Wait for Rahul", "type": "waiting_for", "person": "Rahul", "needs_confirmation": True},
            ],
            "explanation": "Two commitments found",
        })

    async def stream(self, messages):
        yield ""

    async def list_models(self):
        return ["test-model"]


@pytest.mark.asyncio
async def test_gateway_does_not_silently_fallback_on_model_failure():
    result = await LLMGateway(UnavailableProvider()).extract_commitments("Finish the report")
    assert result.candidates == []
    assert result.provider_error
    assert result.used_fallback is False


@pytest.mark.asyncio
async def test_gateway_only_uses_fallback_when_explicitly_requested():
    result = await LLMGateway(UnavailableProvider()).extract_commitments("Finish the report tomorrow", allow_fallback=True)
    assert len(result.candidates) == 1
    assert result.used_fallback is True
    assert result.provider_error


@pytest.mark.asyncio
async def test_gateway_accepts_multiple_structured_candidates():
    result = await LLMGateway(StructuredProvider()).extract_commitments(
        "Send proposal and wait for Rahul",
        context="Known contact: Rahul <rahul@example.com>",
        now=datetime(2026, 11, 2, 10, tzinfo=UTC),
    )
    assert result.used_local_model is True
    assert len(result.candidates) == 2
