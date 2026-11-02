from __future__ import annotations

import enum
from collections.abc import Callable

import httpx


class ConnectivityState(enum.StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    RESUMING = "resuming"
    LIMITED = "limited"


class ConnectivityMonitor:
    def __init__(self) -> None:
        self.state = ConnectivityState.OFFLINE
        self._listeners: list[Callable[[ConnectivityState], None]] = []

    def subscribe(self, listener: Callable[[ConnectivityState], None]) -> None:
        self._listeners.append(listener)

    def set_state(self, state: ConnectivityState) -> None:
        if state == self.state:
            return
        self.state = state
        for listener in self._listeners:
            listener(state)

    async def probe(self, url: str = "https://connectivity-check.invalid", *, timeout: float = 3.0) -> ConnectivityState:
        """Update state from an explicit network probe without changing model selection."""
        previous = self.state
        if previous == ConnectivityState.OFFLINE:
            self.set_state(ConnectivityState.RESUMING)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.head(url)
            state = ConnectivityState.ONLINE if response.is_success else ConnectivityState.LIMITED
        except httpx.HTTPError:
            state = ConnectivityState.OFFLINE
        self.set_state(state)
        return state
