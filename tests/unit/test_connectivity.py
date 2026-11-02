from __future__ import annotations

import pytest

from pactlyn.core.connectivity import ConnectivityMonitor, ConnectivityState


@pytest.mark.asyncio
async def test_connectivity_probe_transitions_without_cloud_fallback(monkeypatch):
    class Response:
        is_success = True

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def head(self, _url):
            return Response()

    monkeypatch.setattr("pactlyn.core.connectivity.httpx.AsyncClient", lambda **_kwargs: Client())
    monitor = ConnectivityMonitor()
    assert await monitor.probe("https://example.test") == ConnectivityState.ONLINE
